"""Wake word detection using Porcupine (Picovoice).

Porcupine runs fully on-device and supports a set of built-in keywords:
"alexa", "americano", "blueberry", "bumblebee", "computer", "grapefruit",
"grasshopper", "hey google", "hey siri", "jarvis", "ok google", "picovoice",
"porcupine", "terminator".

Custom wake words (.ppn files) are also supported via WAKE_WORD_KEYWORD_PATH.

Requires a free Picovoice access key — set PICOVOICE_ACCESS_KEY in .env.
"""

import logging
import time
import struct
import pvporcupine
import pyaudio

from .audio_manager import manager
from .config import settings

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Blocking wake-word listener.

    Usage::
        detector = WakeWordDetector()
        detector.wait_for_wake_word()   # blocks until heard
        detector.close()
    """

    def __init__(self):
        access_key = settings.PICOVOICE_ACCESS_KEY.strip()
        if not access_key:
            raise ValueError("PICOVOICE_ACCESS_KEY must be set in .env to use wake word detection")

        keyword_path = settings.WAKE_WORD_KEYWORD_PATH.strip() if settings.WAKE_WORD_KEYWORD_PATH else None
        keyword = settings.WAKE_WORD_KEYWORD.strip().lower()

        if keyword_path:
            # Custom .ppn model file
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[keyword_path],
                sensitivities=[settings.WAKE_WORD_THRESHOLD],
            )
            label = keyword_path
        else:
            # Built-in keyword
            if not keyword:
                raise ValueError("WAKE_WORD_KEYWORD cannot be empty when wake-word is enabled")
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=[keyword],
                sensitivities=[settings.WAKE_WORD_THRESHOLD],
            )
            label = keyword

        self._cooldown_seconds = max(0.0, float(settings.WAKE_WORD_COOLDOWN_SECONDS))
        self._sample_rate = self._porcupine.sample_rate      # always 16000
        self._frame_length = self._porcupine.frame_length    # always 512

        self._stream = None
        self._open_stream()
        logger.info(
            "Wake word detector ready (Porcupine): keyword='%s', sensitivity=%.2f, cooldown=%.1fs",
            label,
            settings.WAKE_WORD_THRESHOLD,
            self._cooldown_seconds,
        )

    def _open_stream(self) -> None:
        """Open the PyAudio capture stream via the global AudioManager."""
        pa = manager.fresh_pa()
        self._stream = pa.open(
            rate=self._sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self._frame_length,
        )

    def _close_stream(self) -> None:
        """Stop and close the PyAudio capture stream."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def wait_for_wake_word(self) -> None:
        """Block until the wake word is detected."""
        if self._stream is None:
            self._open_stream()

        # Discard stale audio that accumulated while we were away
        frames_to_discard = self._stream.get_read_available()
        if frames_to_discard > 0:
            self._stream.read(frames_to_discard, exception_on_overflow=False)
            logger.debug("Discarded %d stale frames", frames_to_discard)

        logger.info("Listening for wake word …")
        while True:
            pcm_bytes = self._stream.read(self._frame_length, exception_on_overflow=False)
            # Porcupine expects a list/tuple of int16 samples
            pcm = struct.unpack_from(f"{self._frame_length}h", pcm_bytes)
            result = self._porcupine.process(pcm)

            if result >= 0:
                logger.info("Wake word detected! (keyword index %d)", result)

                if self._cooldown_seconds > 0:
                    time.sleep(self._cooldown_seconds)

                # Release the capture device so AudioRecorder can open it.
                self._close_stream()
                return

    def close(self) -> None:
        self._close_stream()
        if self._porcupine is not None:
            self._porcupine.delete()
            self._porcupine = None
