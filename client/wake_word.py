"""
Wake word detection using PicoVoice Porcupine.

Porcupine runs entirely on-device (offline), making it suitable for
always-on listening on resource-constrained hardware like Raspberry Pi.

Get a free AccessKey at: https://console.picovoice.ai/
"""

import logging
import pvporcupine
import pyaudio
import struct

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
        keyword = settings.WAKE_WORD_KEYWORD

        # Accept either a built-in keyword name or a path to a .ppn file
        if keyword.endswith(".ppn"):
            self._porcupine = pvporcupine.create(
                access_key=settings.PORCUPINE_ACCESS_KEY,
                keyword_paths=[keyword],
            )
        else:
            self._porcupine = pvporcupine.create(
                access_key=settings.PORCUPINE_ACCESS_KEY,
                keywords=[keyword],
            )

        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            rate=self._porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self._porcupine.frame_length,
        )
        logger.info("Wake word detector ready: keyword='%s'", keyword)

    def wait_for_wake_word(self) -> None:
        """Block until the wake word is detected."""
        logger.info("Listening for wake word …")
        while True:
            pcm_bytes = self._stream.read(
                self._porcupine.frame_length, exception_on_overflow=False
            )
            pcm = struct.unpack_from(f"{self._porcupine.frame_length}h", pcm_bytes)
            index = self._porcupine.process(pcm)
            if index >= 0:
                logger.info("Wake word detected!")
                return

    def close(self) -> None:
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()
        self._porcupine.delete()
