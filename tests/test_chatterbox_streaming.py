"""Unit tests for audio helpers (no GPU)."""

import numpy as np
import torch

from voice_gpu_server.audio_utils import float_audio_to_pcm16


def test_float_audio_to_pcm16_mono():
    audio = torch.tensor([[-1.0, 0.0, 1.0]], dtype=torch.float32)
    pcm = float_audio_to_pcm16(audio)
    samples = np.frombuffer(pcm, dtype=np.int16)
    assert samples.tolist() == [-32767, 0, 32767]
