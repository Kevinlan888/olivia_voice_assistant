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
        self._calibration_frames = max(3, settings.SILENCE_CALIBRATION_FRAMES)
        self._speech_multiplier = max(1.1, settings.SILENCE_SPEECH_MULTIPLIER)
        self._silence_limit = int(settings.SILENCE_SECONDS * self._rate / self._chunk)
        self._max_chunks = int(settings.MAX_RECORDING_SECONDS * self._rate / self._chunk)
        self._pre_stream = None
        logger.info(
            "AudioRecorder ready: rate=%d calibration_frames=%d speech_mult=%.1f",
            self._rate, self._calibration_frames, self._speech_multiplier,
        )

    def pre_open_stream(self) -> None:
        """Open the mic stream in advance so PyAudio starts buffering immediately.

        Call this BEFORE playing the acknowledgement beep.  Then call record()
        as usual — it will reuse the already-open stream and flush the audio
        captured during the beep, so no initial speech is lost.
        """
        if self._pre_stream is not None:
            return  # already open
        pa = manager.get_pa()
        self._pre_stream = pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )
        logger.debug("Mic stream pre-opened")

    def record(self) -> bytes:
        """Open the mic, record one utterance with VAD, return raw PCM bytes."""
        if self._pre_stream is not None:
            stream = self._pre_stream
            self._pre_stream = None
            # Flush ALL audio buffered while the stream was pre-open (covers
            # the beep duration + any PyAudio open latency).
            stale = stream.get_read_available()
            if stale > 0:
                stream.read(stale, exception_on_overflow=False)
                logger.debug("Flushed %d stale frames from pre-open stream", stale)
        else:
            pa = manager.get_pa()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=settings.CHANNELS,
                rate=self._rate,
                input=True,
                frames_per_buffer=self._chunk,
            )
            # Discard frames buffered during stream open (~100 ms).
            _flush = int(0.1 * self._rate / self._chunk)
            for _ in range(_flush):
                stream.read(self._chunk, exception_on_overflow=False)

        logger.info("Recording … (speak now)")

        # ── Adaptive noise floor calibration ───────────────────────────────────
        # Read a few frames of ambient noise to set the threshold dynamically.
        # This eliminates per-environment manual tuning.
        cal_rms_values = []
        cal_frames: list[bytes] = []
        for _ in range(self._calibration_frames):
            chunk = stream.read(self._chunk, exception_on_overflow=False)
            cal_frames.append(chunk)
            cal_rms_values.append(_rms(chunk))

        noise_floor = float(np.median(cal_rms_values))
        # Clamp noise floor to a sane minimum so dead-silent rooms still work.
        noise_floor = max(noise_floor, 50.0)
        threshold = noise_floor * self._speech_multiplier
        logger.info("Noise floor=%.0f → speech threshold=%.0f", noise_floor, threshold)

        frames: list[bytes] = list(cal_frames)   # keep calibration frames (may contain speech)
        silent_chunks = 0
        total_chunks = len(cal_frames)
        speech_detected = False

        try:
            while total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1

                rms = _rms(chunk)

                if rms < threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                    speech_detected = True

                # Stop on sustained silence — but only after speech was detected,
                # so we don't bail on the brief quiet before the user starts talking.
                if speech_detected and silent_chunks >= self._silence_limit:
                    logger.info("Silence detected — stopping recording.")
                    if silent_chunks <= len(frames):
                        frames = frames[: len(frames) - silent_chunks]
                    break
        finally:
            stream.stop_stream()
            stream.close()

        logger.info("Recorded %d chunks (%.1fs)", total_chunks, total_chunks * self._chunk / self._rate)
        return b"".join(frames)

    def record_ptt(self, button) -> bytes:
        """Record while the PTT button is held; stop when released.

        Args:
            button: PTTButton instance (already confirmed pressed before call).

        Returns raw PCM bytes (int16, mono, SAMPLE_RATE Hz).
        """
        pa = manager.get_pa()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )

        # Flush stale buffer.
        _flush = int(0.1 * self._rate / self._chunk)
        for _ in range(_flush):
            stream.read(self._chunk, exception_on_overflow=False)

        logger.info("PTT recording …")
        frames: list[bytes] = []
        total_chunks = 0

        try:
            while button.is_pressed() and total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1
        finally:
            stream.stop_stream()
            stream.close()

        logger.info("PTT released — recorded %d chunks (%.1fs)", total_chunks, total_chunks * self._chunk / self._rate)
        return b"".join(frames)

    def close(self) -> None:
        if self._pre_stream is not None:
            try:
                self._pre_stream.stop_stream()
                self._pre_stream.close()
            except Exception:
                pass
            self._pre_stream = None
