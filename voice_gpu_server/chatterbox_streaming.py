"""Token-level Chatterbox Turbo streaming (upstream PR #528 pattern).

chatterbox-tts 0.1.3 only exposes batch ``generate()``; this module streams PCM
chunks as speech tokens are decoded so the HTTP client gets audio sooner.
"""

from __future__ import annotations

from typing import Any, Iterator

import torch
import torch.nn.functional as F
from torch import Tensor
from transformers.generation.logits_process import (
    LogitsProcessorList,
    RepetitionPenaltyLogitsProcessor,
    TemperatureLogitsWarper,
    TopKLogitsWarper,
    TopPLogitsWarper,
)

from chatterbox.models.s3gen.const import S3GEN_SIL, S3GEN_SR
from chatterbox.models.s3tokenizer import SPEECH_VOCAB_SIZE
from chatterbox.tts_turbo import punc_norm


from voice_gpu_server.audio_utils import float_audio_to_pcm16


def _patch_chatterbox_flow_streaming() -> None:
    """Backport resemble-ai/chatterbox#528: trim h_masks when streaming (finalize=False).

    chatterbox-tts 0.1.3 trims encoder output ``h`` but not ``h_masks``, causing
    RuntimeError (mask vs activation size mismatch) during S3GenStreamer flush.
    """
    try:
        from chatterbox.models.s3gen.flow import CausalMaskedDiffWithXvec, _repeat_batch_dim
        from chatterbox.models.s3gen.utils.mask import make_pad_mask
    except ImportError:
        return

    if getattr(CausalMaskedDiffWithXvec, "_vgs_streaming_patch", False):
        return

    import logging

    import torch
    from torch.nn import functional as F

    flow_logger = logging.getLogger("chatterbox.models.s3gen.flow")

    @torch.inference_mode()
    def patched_inference(
        self,
        token,
        token_len,
        prompt_token,
        prompt_token_len,
        prompt_feat,
        prompt_feat_len,
        embedding,
        finalize,
        n_timesteps=10,
        noised_mels=None,
        meanflow=False,
    ):
        B = token.size(0)
        embedding = torch.atleast_2d(embedding)
        embedding = F.normalize(embedding, dim=1)
        embedding = self.spk_embed_affine_layer(embedding)

        prompt_token = _repeat_batch_dim(prompt_token, B, ndim=2)
        prompt_token_len = _repeat_batch_dim(prompt_token_len, B, ndim=1)
        prompt_feat = _repeat_batch_dim(prompt_feat, B, ndim=3)
        prompt_feat_len = _repeat_batch_dim(prompt_feat_len, B, ndim=1)
        embedding = _repeat_batch_dim(embedding, B, ndim=2)

        token, token_len = torch.concat([prompt_token, token], dim=1), prompt_token_len + token_len
        mask = (~make_pad_mask(token_len)).unsqueeze(-1).to(embedding)

        if (token >= self.vocab_size).any():
            flow_logger.error(
                "%s>%s out-of-range special tokens in flow", token.max(), self.vocab_size
            )
            token = self.input_embedding(token.long()) * mask

        h, h_masks = self.encoder(token, token_len)
        if finalize is False:
            lookahead_frames = self.pre_lookahead_len * self.token_mel_ratio
            h = h[:, :-lookahead_frames]
            h_masks = h_masks[:, :, :-lookahead_frames]

        h_lengths = h_masks.sum(dim=-1).squeeze(dim=-1)
        mel_len1, mel_len2 = prompt_feat.shape[1], h.shape[1] - prompt_feat.shape[1]
        h = self.encoder_proj(h)

        conds = torch.zeros([B, mel_len1 + mel_len2, self.output_size], device=token.device).to(
            h.dtype
        )
        conds[:, :mel_len1] = prompt_feat
        conds = conds.transpose(1, 2)

        mask = (~make_pad_mask(h_lengths)).unsqueeze(1).to(h)
        if mask.shape[0] != B:
            mask = mask.repeat(B, 1, 1)

        feat, _ = self.decoder(
            mu=h.transpose(1, 2).contiguous(),
            mask=mask,
            spks=embedding,
            cond=conds,
            n_timesteps=n_timesteps,
            noised_mels=noised_mels,
            meanflow=meanflow,
        )
        feat = feat[:, :, mel_len1:]
        assert feat.shape[2] == mel_len2
        return feat, None

    CausalMaskedDiffWithXvec.inference = patched_inference
    CausalMaskedDiffWithXvec._vgs_streaming_patch = True


class S3GenStreamer:
    """Incrementally decode S3 speech tokens into waveform chunks."""

    def __init__(
        self,
        s3gen: Any,
        ref_dict: dict,
        *,
        n_cfm_timesteps: int | None = None,
        crossfade_ms: float = 12.0,
    ) -> None:
        self.s3gen = s3gen
        self.ref_dict = ref_dict
        self.n_cfm_timesteps = n_cfm_timesteps or (2 if s3gen.meanflow else 10)
        self.crossfade_samples = max(0, int(S3GEN_SR * crossfade_ms / 1000.0))

        self.token_buffer: list[Tensor] = []
        self.noised_mels: Tensor | None = None
        self.hift_cache_source = torch.zeros(
            1, 1, 0, device=s3gen.device, dtype=s3gen.dtype
        )
        self.pending_tail: Tensor | None = None
        self.emitted_samples = 0
        self.generated_tokens = 0
        self.finished = False

    def append(self, speech_token: Tensor) -> None:
        if self.finished:
            raise RuntimeError("cannot append tokens after finish()")
        speech_token = torch.atleast_2d(speech_token).to(
            device=self.s3gen.device, dtype=torch.long
        )
        self.token_buffer.append(speech_token)
        self.generated_tokens += speech_token.shape[-1]

    def flush(self, *, finalize: bool = False) -> Tensor | None:
        return self._emit_smoothed(self._decode_available(finalize=finalize), finalize=finalize)

    def finish(self) -> Tensor | None:
        if not self.finished:
            silence = torch.tensor(
                [[S3GEN_SIL, S3GEN_SIL, S3GEN_SIL]],
                dtype=torch.long,
                device=self.s3gen.device,
            )
            self.token_buffer.append(silence)
            self.finished = True
        return self.flush(finalize=True)

    def _ensure_noise(self, mel_frames: int) -> Tensor:
        shape = (1, 80, mel_frames)
        if self.noised_mels is None:
            self.noised_mels = torch.randn(*shape, dtype=self.s3gen.dtype, device=self.s3gen.device)
        elif self.noised_mels.shape[-1] < mel_frames:
            extra = torch.randn(
                1,
                80,
                mel_frames - self.noised_mels.shape[-1],
                dtype=self.s3gen.dtype,
                device=self.s3gen.device,
            )
            self.noised_mels = torch.cat([self.noised_mels, extra], dim=-1)
        return self.noised_mels[:, :, :mel_frames]

    def _decode_available(self, *, finalize: bool) -> Tensor | None:
        if not self.token_buffer:
            return None

        speech_tokens = torch.cat(self.token_buffer, dim=1)
        effective_tokens = speech_tokens.shape[-1]
        if not finalize:
            lookahead = self.s3gen.flow.pre_lookahead_len
            if effective_tokens <= lookahead:
                return None
            effective_tokens -= lookahead

        if effective_tokens <= 0:
            return None

        noised_mels = self._ensure_noise(effective_tokens * self.s3gen.flow.token_mel_ratio)
        output_mels = self.s3gen(
            speech_tokens=speech_tokens,
            ref_wav=None,
            ref_sr=None,
            ref_dict=self.ref_dict,
            n_cfm_timesteps=self.n_cfm_timesteps,
            finalize=finalize,
            skip_vocoder=True,
            noised_mels=noised_mels,
        ).to(dtype=self.s3gen.dtype)

        wav, source = self.s3gen.hift_inference(output_mels, self.hift_cache_source)
        self.hift_cache_source = source.detach()
        wav[:, : len(self.s3gen.trim_fade)] *= self.s3gen.trim_fade

        if wav.shape[-1] <= self.emitted_samples:
            return None

        return wav[:, self.emitted_samples :]

    def _emit_smoothed(self, chunk: Tensor | None, *, finalize: bool) -> Tensor | None:
        if chunk is None or chunk.shape[-1] == 0:
            return None

        if self.crossfade_samples <= 0:
            self.emitted_samples += chunk.shape[-1]
            return chunk

        chunk_len = chunk.shape[-1]
        if not finalize and chunk_len <= self.crossfade_samples:
            return None

        if finalize:
            output = chunk
            if self.pending_tail is not None:
                output = self._join_with_crossfade(self.pending_tail, chunk)
            self.pending_tail = None
            self.emitted_samples += chunk_len
            return output

        emit_len = chunk_len - self.crossfade_samples
        body = chunk[:, :emit_len]
        new_tail = chunk[:, emit_len:].detach().clone()
        output = body
        if self.pending_tail is not None:
            output = self._join_with_crossfade(self.pending_tail, body)
        self.pending_tail = new_tail
        self.emitted_samples += emit_len
        return output

    def _join_with_crossfade(self, left: Tensor, right: Tensor) -> Tensor:
        overlap = min(self.crossfade_samples, left.shape[-1], right.shape[-1])
        if overlap <= 0:
            return torch.cat([left, right], dim=1)

        fade_out = torch.linspace(1.0, 0.0, overlap, device=right.device, dtype=right.dtype).unsqueeze(
            0
        )
        fade_in = 1.0 - fade_out
        crossed = left[:, -overlap:] * fade_out + right[:, :overlap] * fade_in

        parts: list[Tensor] = []
        if left.shape[-1] > overlap:
            parts.append(left[:, :-overlap])
        parts.append(crossed)
        if right.shape[-1] > overlap:
            parts.append(right[:, overlap:])
        return torch.cat(parts, dim=1)


def iter_inference_turbo(
    t3: Any,
    t3_cond: Any,
    text_tokens: Tensor,
    *,
    temperature: float = 0.8,
    top_k: int = 1000,
    top_p: float = 0.95,
    repetition_penalty: float = 1.2,
    max_gen_len: int = 1000,
) -> Iterator[Tensor]:
    """Yield Turbo speech tokens incrementally (no tqdm progress bar)."""
    logits_processors = LogitsProcessorList()
    if 0 < temperature != 1.0:
        logits_processors.append(TemperatureLogitsWarper(temperature))
    if top_k > 0:
        logits_processors.append(TopKLogitsWarper(top_k))
    if top_p < 1.0:
        logits_processors.append(TopPLogitsWarper(top_p))
    if repetition_penalty != 1.0:
        logits_processors.append(RepetitionPenaltyLogitsProcessor(repetition_penalty))

    speech_start_token = t3.hp.start_speech_token * torch.ones_like(text_tokens[:, :1])
    embeds, _ = t3.prepare_input_embeds(
        t3_cond=t3_cond,
        text_tokens=text_tokens,
        speech_tokens=speech_start_token,
        cfg_weight=0.0,
    )

    generated_speech_tokens: list[Tensor] = []
    llm_outputs = t3.tfmr(inputs_embeds=embeds, use_cache=True)
    hidden_states = llm_outputs[0]
    past_key_values = llm_outputs.past_key_values

    speech_logits = t3.speech_head(hidden_states[:, -1:])
    processed_logits = logits_processors(speech_start_token, speech_logits[:, -1, :])
    next_speech_token = torch.multinomial(F.softmax(processed_logits, dim=-1), num_samples=1)

    generated_speech_tokens.append(next_speech_token)
    current_speech_token = next_speech_token
    if torch.all(current_speech_token == t3.hp.stop_speech_token):
        return
    yield current_speech_token

    for _ in range(max_gen_len):
        current_speech_embed = t3.speech_emb(current_speech_token)
        llm_outputs = t3.tfmr(
            inputs_embeds=current_speech_embed,
            past_key_values=past_key_values,
            use_cache=True,
        )
        hidden_states = llm_outputs[0]
        past_key_values = llm_outputs.past_key_values
        speech_logits = t3.speech_head(hidden_states)

        input_ids = torch.cat(generated_speech_tokens, dim=1)
        processed_logits = logits_processors(input_ids, speech_logits[:, -1, :])
        if torch.all(processed_logits == -float("inf")):
            break

        next_speech_token = torch.multinomial(F.softmax(processed_logits, dim=-1), num_samples=1)
        generated_speech_tokens.append(next_speech_token)
        current_speech_token = next_speech_token
        if torch.all(next_speech_token == t3.hp.stop_speech_token):
            break
        yield current_speech_token


def stream_turbo_pcm(
    model: Any,
    text: str,
    *,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    chunk_tokens: int,
    crossfade_ms: float,
    max_gen_len: int,
    n_cfm_timesteps: int,
) -> Iterator[bytes]:
    """Yield 16-bit PCM chunks while Turbo speech is still being generated."""
    _patch_chatterbox_flow_streaming()
    if model.conds is None:
        raise RuntimeError("Voice conditionals not prepared — call prepare_conditionals first")

    text = punc_norm(text)
    text_tokens = model.tokenizer(text, return_tensors="pt", padding=True, truncation=True)
    text_tokens = text_tokens.input_ids.to(model.device)

    streamer = S3GenStreamer(
        model.s3gen,
        model.conds.gen,
        n_cfm_timesteps=n_cfm_timesteps,
        crossfade_ms=crossfade_ms,
    )

    with torch.inference_mode():
        for token in iter_inference_turbo(
            model.t3,
            model.conds.t3,
            text_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            max_gen_len=max_gen_len,
        ):
            if int(token.item()) >= SPEECH_VOCAB_SIZE:
                continue

            streamer.append(token)
            if streamer.generated_tokens % chunk_tokens == 0:
                wav = streamer.flush(finalize=False)
                if wav is not None:
                    yield float_audio_to_pcm16(wav)

        wav = streamer.finish()
        if wav is not None:
            yield float_audio_to_pcm16(wav)
