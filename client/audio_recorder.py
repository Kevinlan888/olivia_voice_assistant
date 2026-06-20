"""
Chunk-driven microphone recorder with Silero neural-network VAD.

Assembles one utterance from externally supplied PCM chunks.
After refactor, this module owns only VAD-based utterance assembly
and completion rules. It does NOT open or close any microphone stream.

Usage::

    recorder = AudioRecorder(on_speech_chunk=my_callback)
    recorder.start_utterance(prebuffer_chunks)
    for chunk in mic:
        if recorder.append_chunk(chunk):
            break
    pcm = recorder.finish_utterance()
"""

import logging
from typing import Callable

from .config import settings
from .silero_vad import SileroVAD

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Chunk-driven utterance assembler with Silero VAD.

    Receives PCM chunks from an external source (SharedMicrophone)
    and assembles one utterance per session. Call ``start_utterance()``
    to begin, feed chunks via ``append_chunk()``, and collect the
    result with ``finish_utterance()``.
    """

    def __init__(
        self,
        on_speech_chunk: Callable[[bytes], None] | None = None,
    ):
        self._rate = settings.SAMPLE_RATE
        self._chunk = settings.CHUNK_FRAMES
        self._speech_threshold = settings.SILERO_SPEECH_THRESHOLD
        self._neg_threshold = max(self._speech_threshold - 0.15, 0.01)
        self._silence_limit = int(settings.SILENCE_SECONDS * self._rate / self._chunk)
        self._min_chunks = int(settings.MIN_RECORDING_SECONDS * self._rate / self._chunk)
        self._max_chunks = int(settings.MAX_RECORDING_SECONDS * self._rate / self._chunk)
        self._vad = SileroVAD(sample_rate=self._rate)
        self._on_speech_chunk = on_speech_chunk

        # Per-utterance state (set by start_utterance)
        self._frames: list[bytes] = []
        self._silent_chunks = 0
        self._total_chunks = 0
        self._speech_detected = False

        logger.info(
            "AudioRecorder ready: rate=%d chunk=%d speech_thr=%.2f neg_thr=%.2f silence_chunks=%d",
            self._rate, self._chunk, self._speech_threshold, self._neg_threshold, self._silence_limit,
        )

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def is_speech_started(self) -> bool:
        """True once VAD has detected speech in the current utterance."""
        return self._speech_detected

    def start_utterance(self, prebuffer: list[bytes]) -> None:
        """Begin a new utterance, seeding it with prebuffer chunks
        captured while listening for the wake word.

        Resets VAD state, stores prebuffer as the first frames, and
        resets silence / chunk counters.

        Args:
            prebuffer: list of PCM chunks (bytes) to prepend.
        """
        self._vad.reset()
        self._frames = list(prebuffer)
        self._total_chunks = len(prebuffer)
        self._silent_chunks = 0
        self._speech_detected = False

        if self._on_speech_chunk:
            for chunk in prebuffer:
                self._on_speech_chunk(chunk)

        logger.info(
            "Utterance started: %d prebuffer chunks (%.1fs)",
            len(prebuffer),
            len(prebuffer) * self._chunk / self._rate,
        )

    def append_chunk(self, chunk: bytes) -> bool:
        """Append one live chunk and return True if the utterance is
        complete (silence after speech, or max duration reached).

        If speech has been detected and an ``on_speech_chunk`` callback
        is set, the chunk is forwarded immediately.

        Args:
            chunk: raw PCM bytes (CHUNK_FRAMES * 2 bytes).

        Returns:
            True if utterance is complete, False if still recording.
        """
        self._frames.append(chunk)
        self._total_chunks += 1

        prob = self._vad(chunk)

        if prob >= self._speech_threshold:
            self._speech_detected = True
            self._silent_chunks = 0
        elif self._speech_detected and prob < self._neg_threshold:
            # Only count silence after speech has started,
            # and only when prob drops well below threshold
            self._silent_chunks += 1
        elif self._speech_detected:
            # Between neg_threshold and speech_threshold — hysteresis zone
            pass

        # In wake-word mode, upload should stay continuous from utterance start.
        # VAD still decides when to stop and whether the utterance was empty.
        if self._on_speech_chunk:
            self._on_speech_chunk(chunk)

        # Stop on sustained silence — after speech was detected
        # and the minimum recording duration has elapsed.
        if (self._speech_detected
                and self._total_chunks >= self._min_chunks
                and self._silent_chunks >= self._silence_limit):
            logger.info("Silence detected — stopping recording.")
            return True

        # Hard cap at max duration
        if self._total_chunks >= self._max_chunks:
            logger.info("Max recording duration reached — stopping.")
            return True

        return False

    def finish_utterance(self) -> bytes | None:
        """Return the assembled PCM for the completed utterance,
        or None if no valid speech was detected (empty utterance).

        Trims trailing silence and validates minimum duration.
        """
        if not self._speech_detected:
            logger.info("No speech detected in utterance — discarding.")
            return None

        # Trim trailing silent frames
        if self._silent_chunks > 0 and self._silent_chunks <= len(self._frames):
            self._frames = self._frames[:len(self._frames) - self._silent_chunks]

        total = len(self._frames)
        logger.info("Utterance complete: %d chunks (%.1fs)", total, total * self._chunk / self._rate)
        return b"".join(self._frames)

    def close(self) -> None:
        """Release resources (currently a no-op, kept for API compat)."""
        pass
