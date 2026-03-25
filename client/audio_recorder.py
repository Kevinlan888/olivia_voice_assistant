"""
Microphone recorder with energy-based Voice Activity Detection (VAD).

Records until a configurable period of silence or a maximum duration,
then returns the raw PCM bytes (int16, 16 kHz, mono).
"""

import logging
import math
import struct
import pyaudio

from .config import settings

logger = logging.getLogger(__name__)


def _rms(chunk_bytes: bytes) -> float:
    """Root-mean-square energy of a raw int16 PCM chunk."""
    count = len(chunk_bytes) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", chunk_bytes)
    sum_sq = sum(s * s for s in shorts)
    return math.sqrt(sum_sq / count)


class AudioRecorder:
    """Capture one utterance from the microphone and return PCM bytes.

    Uses simple energy-based VAD:
      - Recording starts immediately.
      - After the user stops speaking (RMS stays below SILENCE_THRESHOLD
        for SILENCE_SECONDS), recording stops automatically.
      - Hard capped at MAX_RECORDING_SECONDS.
    """

    def __init__(self):
        self._pa = pyaudio.PyAudio()
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
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )
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
        self._pa.terminate()
