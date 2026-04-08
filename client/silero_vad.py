"""
Silero VAD wrapper using ONNX Runtime — no PyTorch dependency.

Provides per-chunk speech probability for 16 kHz / 512-sample audio.
Model is auto-downloaded on first use.
"""

import logging
import os
import urllib.request

import numpy as np
import onnxruntime

logger = logging.getLogger(__name__)

_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)
_MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "silero_vad.onnx")


def _ensure_model() -> str:
    """Download the Silero VAD ONNX model if it doesn't exist locally."""
    if os.path.isfile(_MODEL_PATH):
        return _MODEL_PATH
    os.makedirs(_MODEL_DIR, exist_ok=True)
    logger.info("Downloading Silero VAD model → %s …", _MODEL_PATH)
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    logger.info("Silero VAD model downloaded.")
    return _MODEL_PATH


class SileroVAD:
    """Lightweight Silero VAD v5 running on ONNX Runtime (CPU).

    Usage::

        vad = SileroVAD()
        vad.reset()                       # between utterances
        prob = vad(pcm_int16_bytes)       # 512-sample chunk → float [0,1]
    """

    def __init__(self, sample_rate: int = 16000):
        if sample_rate not in (8000, 16000):
            raise ValueError(f"Silero VAD supports 8000/16000 Hz, got {sample_rate}")
        self._sr = sample_rate
        self._context_size = 64 if sample_rate == 16000 else 32

        path = _ensure_model()
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.reset()
        logger.info("Silero VAD loaded (ONNX, sr=%d, context=%d)", self._sr, self._context_size)

    # ── public API ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear LSTM hidden state + context between utterances."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self._context_size), dtype=np.float32)

    def __call__(self, chunk_bytes: bytes) -> float:
        """Return speech probability [0, 1] for a single PCM int16 chunk.

        *chunk_bytes* must contain exactly 512 samples (16 kHz) or 256 (8 kHz).
        """
        samples = np.frombuffer(chunk_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio = samples[np.newaxis, :]  # (1, num_samples)

        # Prepend context (matches upstream OnnxWrapper)
        x = np.concatenate([self._context, audio], axis=1)

        ort_inputs = {
            "input": x,
            "state": self._state,
            "sr": np.array(self._sr, dtype=np.int64),
        }
        out, state = self._session.run(None, ort_inputs)

        self._state = state
        self._context = x[:, -self._context_size:]
        return float(out.squeeze())
