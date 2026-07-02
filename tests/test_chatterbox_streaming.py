"""Unit tests for audio helpers and streaming patches (no GPU)."""

import numpy as np
import torch

from voice_gpu_server.audio_utils import float_audio_to_pcm16
from voice_gpu_server.chatterbox_streaming import _patch_chatterbox_flow_streaming


def test_float_audio_to_pcm16_mono():
    audio = torch.tensor([[-1.0, 0.0, 1.0]], dtype=torch.float32)
    pcm = float_audio_to_pcm16(audio)
    samples = np.frombuffer(pcm, dtype=np.int16)
    assert samples.tolist() == [-32767, 0, 32767]


def test_flow_streaming_patch_is_idempotent():
    _patch_chatterbox_flow_streaming()
    _patch_chatterbox_flow_streaming()
