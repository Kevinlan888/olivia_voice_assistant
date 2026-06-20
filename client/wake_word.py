"""Chunk-driven wake word detection using Porcupine (Picovoice).

Porcupine runs fully on-device and supports a set of built-in keywords:
"alexa", "americano", "blueberry", "bumblebee", "computer", "grapefruit",
"grasshopper", "hey google", "hey siri", "jarvis", "ok google", "picovoice",
"porcupine", "terminator".

Custom wake words (.ppn files) are also supported via WAKE_WORD_KEYWORD_PATH.

Requires a free Picovoice access key — set PICOVOICE_ACCESS_KEY in .env.

After refactor, this module owns only Porcupine initialization and
frame evaluation. It does NOT open or close any microphone stream.
The main loop feeds PCM chunks via ``process_chunk()``.
"""

import logging
import os
import sys
import struct

import pvporcupine

from .config import settings

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Chunk-driven wake word recognizer using Porcupine.

    Usage::

        detector = WakeWordDetector()
        for chunk in mic:
            if detector.process_chunk(chunk):
                # wake word detected
                break
        detector.close()
    """

    def __init__(self):
        access_key = settings.PICOVOICE_ACCESS_KEY.strip()
        if not access_key:
            raise ValueError("PICOVOICE_ACCESS_KEY must be set in .env to use wake word detection")

        keyword_path = settings.WAKE_WORD_KEYWORD_PATH.strip() if settings.WAKE_WORD_KEYWORD_PATH else None
        keyword = settings.WAKE_WORD_KEYWORD.strip().lower()

        if keyword_path:
            # Resolve relative paths against PyInstaller bundle dir when frozen.
            if not os.path.isabs(keyword_path) and getattr(sys, "frozen", False):
                keyword_path = os.path.join(sys._MEIPASS, keyword_path)
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

        self._sample_rate = self._porcupine.sample_rate      # always 16000
        self._frame_length = self._porcupine.frame_length    # always 512

        logger.info(
            "Wake word detector ready (Porcupine): keyword='%s', sensitivity=%.2f",
            label,
            settings.WAKE_WORD_THRESHOLD,
        )

    def process_chunk(self, pcm_chunk: bytes) -> bool:
        """Feed one PCM chunk to Porcupine and return True if the wake
        word is detected.

        Args:
            pcm_chunk: raw PCM bytes, exactly frame_length * 2 bytes
                       (int16 samples at 16 kHz).

        Returns:
            True if wake word detected, False otherwise.
        """
        # Porcupine expects a tuple/list of int16 samples
        pcm = struct.unpack_from(f"{self._frame_length}h", pcm_chunk)
        result = self._porcupine.process(pcm)

        if result >= 0:
            logger.info("Wake word detected! (keyword index %d)", result)
            return True
        return False

    def close(self) -> None:
        """Release Porcupine resources."""
        if self._porcupine is not None:
            self._porcupine.delete()
            self._porcupine = None
