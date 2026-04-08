"""
Microphone recorder with Silero neural-network Voice Activity Detection (VAD).

Records until a configurable period of silence or a maximum duration,
then returns the raw PCM bytes (int16, 16 kHz, mono).
"""

import logging
import pyaudio

from .audio_manager import manager
from .config import settings
from .silero_vad import SileroVAD

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Capture one utterance from the microphone and return PCM bytes.

    Uses Silero VAD (neural network) for robust speech detection:
      - Recording starts immediately.
      - After the user stops speaking (speech probability stays below threshold
        for SILENCE_SECONDS), recording stops automatically.
      - Hard capped at MAX_RECORDING_SECONDS.
    """

    def __init__(self):
        self._rate = settings.SAMPLE_RATE
        self._chunk = settings.CHUNK_FRAMES
        self._speech_threshold = settings.SILERO_SPEECH_THRESHOLD
        self._neg_threshold = max(self._speech_threshold - 0.15, 0.01)
        self._silence_limit = int(settings.SILENCE_SECONDS * self._rate / self._chunk)
        self._min_chunks = int(settings.MIN_RECORDING_SECONDS * self._rate / self._chunk)
        self._max_chunks = int(settings.MAX_RECORDING_SECONDS * self._rate / self._chunk)
        self._pre_stream = None
        self._vad = SileroVAD(sample_rate=self._rate)
        logger.info(
            "AudioRecorder ready: rate=%d chunk=%d speech_thr=%.2f neg_thr=%.2f silence_chunks=%d",
            self._rate, self._chunk, self._speech_threshold, self._neg_threshold, self._silence_limit,
        )

    def pre_open_stream(self) -> None:
        """Open the mic stream before the beep so it's ready for recording.

        Call this BEFORE playing the acknowledgement beep.  record() will reuse
        the already-open stream and flush the frames captured during the beep.
        No calibration is needed — Silero VAD handles speech detection directly.
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
        logger.debug("Pre-opened mic stream for recording.")

    def record(self) -> bytes:
        """Open the mic, record one utterance with Silero VAD, return raw PCM bytes."""
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

        # Reset VAD state for a fresh utterance
        self._vad.reset()

        logger.info("Recording … (speak now, Silero VAD thr=%.2f)", self._speech_threshold)

        frames: list[bytes] = []
        silent_chunks = 0
        total_chunks = 0
        speech_detected = False
        log_interval = max(1, int(0.5 * self._rate / self._chunk))  # ~0.5s

        try:
            while total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1

                prob = self._vad(chunk)

                if prob >= self._speech_threshold:
                    speech_detected = True
                    silent_chunks = 0
                elif speech_detected and prob < self._neg_threshold:
                    # Only count silence after speech has started,
                    # and only when prob drops well below threshold
                    silent_chunks += 1
                elif speech_detected:
                    # Between neg_threshold and speech_threshold — don't reset,
                    # but don't increment either (hysteresis zone)
                    pass

                # Periodic logging for diagnostics
                if total_chunks % log_interval == 0:
                    logger.debug(
                        "chunk=%d prob=%.3f speech=%s silent_run=%d/%d",
                        total_chunks, prob, speech_detected, silent_chunks, self._silence_limit,
                    )

                # Stop on sustained silence — after speech was detected
                # and the minimum recording duration has elapsed.
                if (speech_detected
                        and total_chunks >= self._min_chunks
                        and silent_chunks >= self._silence_limit):
                    logger.info("Silence detected — stopping recording.")
                    # Trim trailing silent frames
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
