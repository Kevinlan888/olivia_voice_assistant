"""
Microphone recorder with energy-based Voice Activity Detection (VAD).

Records until a configurable period of silence or a maximum duration,
then returns the raw PCM bytes (int16, 16 kHz, mono).
"""

import logging
import pyaudio
import numpy as np

from .audio_manager import manager
from .config import settings

logger = logging.getLogger(__name__)


def _rms(chunk_bytes: bytes) -> float:
    """Root-mean-square energy of a raw int16 PCM chunk (numpy, no GIL pressure)."""
    samples = np.frombuffer(chunk_bytes, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


class AudioRecorder:
    """Capture one utterance from the microphone and return PCM bytes.

    Uses simple energy-based VAD:
      - Recording starts immediately.
      - After the user stops speaking (RMS stays below SILENCE_THRESHOLD
        for SILENCE_SECONDS), recording stops automatically.
      - Hard capped at MAX_RECORDING_SECONDS.
    """

    def __init__(self):
        self._rate = settings.SAMPLE_RATE
        self._chunk = settings.CHUNK_FRAMES
        self._silence_threshold = settings.SILENCE_THRESHOLD
        self._silence_limit = int(settings.SILENCE_SECONDS * self._rate / self._chunk)
        self._max_chunks = int(settings.MAX_RECORDING_SECONDS * self._rate / self._chunk)
        logger.info(
            "AudioRecorder ready: rate=%d silence_threshold=%.0f",
            self._rate, self._silence_threshold,
        )

    def record(self) -> bytes:
        """Open the mic, record one utterance, return raw PCM bytes."""
        # Re-use the existing PortAudio context — no need to terminate/recreate
        # it after the wake-word stream closed (same direction: input → input).
        # fresh_pa() would add ~200 ms re-init latency and overflow the ALSA
        # hardware buffer before we start reading, causing a gap at the start.
        pa = manager.get_pa()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )

        # Discard any stale frames buffered during stream open.
        _flush = int(0.1 * self._rate / self._chunk)   # ~100 ms
        for _ in range(_flush):
            stream.read(self._chunk, exception_on_overflow=False)

        logger.info("Recording … (speak now)")

        frames: list[bytes] = []
        silent_chunks = 0
        total_chunks = 0

        try:
            while total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1

                if _rms(chunk) < self._silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0  # reset on speech

                if silent_chunks >= self._silence_limit and total_chunks > self._silence_limit:
                    logger.info("Silence detected — stopping recording.")
                    break
        finally:
            stream.stop_stream()
            stream.close()

        logger.info("Recorded %d chunks (%.1fs)", total_chunks, total_chunks * self._chunk / self._rate)
        return b"".join(frames)

    def close(self) -> None:
        pass  # PyAudio lifecycle is managed by AudioManager
