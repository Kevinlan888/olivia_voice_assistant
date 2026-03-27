"""Wake word detection using openWakeWord.

openWakeWord runs fully on-device and supports built-in pre-trained models
such as "alexa", "hey jarvis", and others.
"""

import logging
import time
import numpy as np
import openwakeword
from openwakeword.model import Model
import pyaudio

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
        keyword = settings.WAKE_WORD_KEYWORD.strip().lower()
        if not keyword:
            raise ValueError("WAKE_WORD_KEYWORD cannot be empty when wake-word is enabled")

        # Ensure built-in model assets are present locally.
        openwakeword.utils.download_models()

        self._model_name = keyword
        self._threshold = settings.WAKE_WORD_THRESHOLD
        self._required_hits = max(1, int(settings.WAKE_WORD_CONSECUTIVE_HITS))
        self._cooldown_seconds = max(0.0, float(settings.WAKE_WORD_COOLDOWN_SECONDS))
        self._model = Model(wakeword_models=[self._model_name])
        self._sample_rate = 16000
        self._frame_length = 1280  # 80 ms at 16 kHz (recommended by openWakeWord)

        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            rate=self._sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self._frame_length,
        )
        logger.info(
            "Wake word detector ready: model='%s', threshold=%.2f hits=%d cooldown=%.1fs",
            self._model_name,
            self._threshold,
            self._required_hits,
            self._cooldown_seconds,
        )

    def wait_for_wake_word(self) -> None:
        """Block until the wake word is detected."""
        logger.info("Listening for wake word …")
        hits = 0
        while True:
            pcm_bytes = self._stream.read(self._frame_length, exception_on_overflow=False)
            pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
            scores = self._model.predict(pcm)
            score = float(scores.get(self._model_name, 0.0))

            if score >= self._threshold:
                hits += 1
            else:
                hits = 0

            if hits >= self._required_hits:
                logger.info("Wake word detected! model='%s' score=%.3f", self._model_name, score)

                # Reset model state if supported to avoid stale high scores.
                reset_fn = getattr(self._model, "reset", None)
                if callable(reset_fn):
                    reset_fn()

                if self._cooldown_seconds > 0:
                    time.sleep(self._cooldown_seconds)
                return

    def close(self) -> None:
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()
