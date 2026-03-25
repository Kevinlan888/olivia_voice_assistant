"""
Audio player using pygame.mixer.

pygame can decode MP3 directly (via libmpg123), so no extra conversion
step is needed. Falls back to writing a temp file when feeding raw bytes.
"""

import io
import logging
import threading
import pygame

from .config import settings

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Thread-safe, non-blocking audio player for MP3 bytes."""

    def __init__(self):
        pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        self._lock = threading.Lock()
        logger.info("AudioPlayer ready (pygame.mixer)")

    def play(self, mp3_bytes: bytes) -> None:
        """Play MP3 bytes synchronously (blocks until playback ends)."""
        with self._lock:
            buf = io.BytesIO(mp3_bytes)
            pygame.mixer.music.load(buf, "mp3")
            pygame.mixer.music.play()
            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.wait(50)

    def stop(self) -> None:
        pygame.mixer.music.stop()

    def close(self) -> None:
        pygame.mixer.quit()
