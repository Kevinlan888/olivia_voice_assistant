"""Single-owner microphone capture component.

The only module allowed to open a PyAudio input stream. All other
input-side consumers (wake word detector, audio recorder) receive
PCM chunks from this component instead of opening their own streams.

Usage::

    mic = SharedMicrophone()
    for chunk in mic:
        # chunk is bytes, exactly CHUNK_FRAMES * 2 bytes (int16)
        ...
    mic.close()
"""

import logging
import struct

import pyaudio

from .audio_manager import manager
from .config import settings

logger = logging.getLogger(__name__)


class SharedMicrophone:
    """Single-owner microphone capture.

    Opens the input device once at construction and provides an
    iterator over fixed-size PCM chunks (int16, mono, SAMPLE_RATE Hz).

    On transient read errors, returns a silence chunk so the main loop
    does not stall. After repeated failures, attempts stream recreation.
    """

    MAX_CONSECUTIVE_ERRORS = 5

    def __init__(self) -> None:
        self._rate = settings.SAMPLE_RATE
        self._channels = settings.CHANNELS
        self._chunk_frames = settings.CHUNK_FRAMES
        self._chunk_bytes = self._chunk_frames * 2  # int16 = 2 bytes
        self._closed = False
        self._consecutive_errors = 0
        self._stream = None
        self._open_stream()

    # ── Iterator protocol ──────────────────────────────────────────────

    def __iter__(self) -> "SharedMicrophone":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        return self.read_chunk()

    # ── Public API ─────────────────────────────────────────────────────

    def read_chunk(self) -> bytes:
        """Read one PCM chunk.

        On transient read errors, logs a warning and returns a silence
        chunk so the caller can continue without stalling. After
        ``MAX_CONSECUTIVE_ERRORS`` failures, attempts stream recreation.

        Returns:
            bytes of length CHUNK_FRAMES * 2 (int16 samples).
        """
        if self._closed:
            raise StopIteration

        try:
            chunk = self._stream.read(
                self._chunk_frames, exception_on_overflow=False
            )
            self._consecutive_errors = 0
            return chunk
        except OSError as exc:
            self._consecutive_errors += 1
            logger.warning(
                "Mic read error (%d/%d): %s",
                self._consecutive_errors,
                self.MAX_CONSECUTIVE_ERRORS,
                exc,
            )
            if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                logger.error("Too many consecutive read errors, recreating stream")
                try:
                    self._recreate_stream()
                except Exception as recreate_exc:
                    logger.error("Stream recreation failed: %s", recreate_exc)
                self._consecutive_errors = 0
            return b"\x00" * self._chunk_bytes

    def close(self) -> None:
        """Stop and close the input stream."""
        self._closed = True
        self._close_stream()

    # ── Internal ───────────────────────────────────────────────────────

    def _open_stream(self) -> None:
        """Open the PyAudio input stream."""
        pa = manager.get_pa()
        self._stream = pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk_frames,
        )
        logger.info(
            "SharedMicrophone opened: rate=%d channels=%d chunk_frames=%d",
            self._rate,
            self._channels,
            self._chunk_frames,
        )

    def _close_stream(self) -> None:
        """Stop and close the PyAudio input stream (best-effort)."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _recreate_stream(self) -> None:
        """Close the old stream and open a new one via ``manager.fresh_pa()``.

        This is the only place ``fresh_pa()`` is called at runtime.
        It handles the rare case where PortAudio gets into a bad state.
        """
        self._close_stream()
        pa = manager.fresh_pa()
        self._stream = pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk_frames,
        )
        logger.info("SharedMicrophone stream recreated after errors")
