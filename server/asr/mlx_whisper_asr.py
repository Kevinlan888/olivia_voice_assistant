import struct
import time
import logging

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)

# Model name → HuggingFace repo mapping for mlx-community converted weights
_MLX_HF_REPOS = {
    "tiny":     "mlx-community/whisper-tiny",
    "tiny.en":  "mlx-community/whisper-tiny.en",
    "base":     "mlx-community/whisper-base",
    "base.en":  "mlx-community/whisper-base.en",
    "small":    "mlx-community/whisper-small",
    "small.en": "mlx-community/whisper-small.en",
    "medium":   "mlx-community/whisper-medium",
    "medium.en":"mlx-community/whisper-medium.en",
    "large":    "mlx-community/whisper-large",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MLXWhisperASR:
    """Synchronous wrapper around mlx-whisper.

    Designed to be called via asyncio.to_thread() from async code.
    """

    def __init__(self):
        import mlx_whisper  # noqa: F401 – eager import to validate availability

        self._repo = _MLX_HF_REPOS.get(settings.WHISPER_MODEL, settings.WHISPER_MODEL)
        logger.info(
            "Loading MLX Whisper model '%s' (repo: %s) …",
            settings.WHISPER_MODEL,
            self._repo,
        )

        # Warm up: run a tiny silent transcription so the model weights are loaded
        t0 = time.perf_counter()
        mlx_whisper.transcribe(
            np.zeros(16000, dtype=np.float32),
            path_or_hf_repo=self._repo,
            verbose=False,
        )
        elapsed = time.perf_counter() - t0
        logger.info("MLX Whisper model loaded in %.1f s.", elapsed)

    # ------------------------------------------------------------------
    def transcribe(self, raw_pcm: bytes) -> str:
        """Transcribe raw PCM bytes (int16, 16 kHz, mono) → text string."""
        import mlx_whisper

        audio_np = self._pcm_to_float32(raw_pcm)

        lang = None if settings.WHISPER_LANGUAGE == "auto" else settings.WHISPER_LANGUAGE
        result = mlx_whisper.transcribe(
            audio_np,
            path_or_hf_repo=self._repo,
            language=lang,
            verbose=False,
        )

        language = result.get("language", "unknown")
        logger.info("Detected language: %s", language)

        text = result.get("text", "")
        return text.strip()

    # ------------------------------------------------------------------
    @staticmethod
    def _pcm_to_float32(raw_pcm: bytes) -> np.ndarray:
        """Convert 16-bit PCM bytes to float32 numpy array in [-1, 1]."""
        if len(raw_pcm) < 2:
            return np.zeros(1, dtype=np.float32)

        num_samples = len(raw_pcm) // 2
        samples = struct.unpack(f"<{num_samples}h", raw_pcm[: num_samples * 2])
        audio_np = np.array(samples, dtype=np.float32) / 32768.0
        return audio_np
