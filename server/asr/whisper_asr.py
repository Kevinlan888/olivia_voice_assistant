import io
import struct
import wave
import logging
import numpy as np
from faster_whisper import WhisperModel

from ..config import settings

logger = logging.getLogger(__name__)


class WhisperASR:
    """Synchronous wrapper around faster-whisper.
    
    Designed to be called via asyncio.to_thread() from async code.
    The model is loaded once and reused across all requests.
    """

    def __init__(self):
        logger.info(
            "Loading Whisper model '%s' on %s (%s) …",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
            settings.WHISPER_COMPUTE_TYPE,
        )
        self._model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
        logger.info("Whisper model loaded.")

    # ------------------------------------------------------------------
    def transcribe(self, raw_pcm: bytes) -> str:
        """Transcribe raw PCM bytes (int16, 16 kHz, mono) → text string."""
        audio_np = self._pcm_to_float32(raw_pcm)

        segments, info = self._model.transcribe(
            audio_np,
            beam_size=5,
            language=None,          # auto-detect; pin to "zh" for Chinese-only
            vad_filter=True,        # skip silent segments automatically
            vad_parameters={"min_silence_duration_ms": 500},
        )
        logger.info("Detected language: %s (%.0f%%)", info.language, info.language_probability * 100)

        text = " ".join(seg.text.strip() for seg in segments)
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
