"""Unit tests for chunk-driven WakeWordDetector.

Uses a fake Porcupine engine to avoid hardware / API key dependency.
"""

import struct
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


def _silence_chunk(frame_length: int = 512) -> bytes:
    return b"\x00" * (frame_length * 2)


def _speech_chunk(frame_length: int = 512) -> bytes:
    return struct.pack(f"{frame_length}h", *([8000] * frame_length))


class _FakePorcupine:
    """Mimics pvporcupine.Porcupine with controllable detection."""

    def __init__(self, detect_on_chunks: list[int] | None = None):
        self._detect_on = set(detect_on_chunks or [])
        self._call_count = 0
        self.sample_rate = 16000
        self.frame_length = 512
        self.deleted = False

    def process(self, pcm):
        idx = self._call_count
        self._call_count += 1
        if idx in self._detect_on:
            return 0  # keyword index
        return -1

    def delete(self):
        self.deleted = True


class TestWakeWordProcessChunk(unittest.TestCase):
    """Test process_chunk() detection logic."""

    @patch("client.wake_word.pvporcupine")
    @patch("client.wake_word.settings")
    def test_no_detection_returns_false(self, mock_settings, mock_pv):
        mock_settings.PICOVOICE_ACCESS_KEY = "test-key"
        mock_settings.WAKE_WORD_KEYWORD = "porcupine"
        mock_settings.WAKE_WORD_KEYWORD_PATH = ""
        mock_settings.WAKE_WORD_THRESHOLD = 0.5

        fake_porc = _FakePorcupine(detect_on_chunks=[])
        mock_pv.create.return_value = fake_porc

        from client.wake_word import WakeWordDetector
        detector = WakeWordDetector()

        chunk = _silence_chunk()
        result = detector.process_chunk(chunk)
        self.assertFalse(result)

        detector.close()
        self.assertTrue(fake_porc.deleted)

    @patch("client.wake_word.pvporcupine")
    @patch("client.wake_word.settings")
    def test_detection_returns_true(self, mock_settings, mock_pv):
        mock_settings.PICOVOICE_ACCESS_KEY = "test-key"
        mock_settings.WAKE_WORD_KEYWORD = "porcupine"
        mock_settings.WAKE_WORD_KEYWORD_PATH = ""
        mock_settings.WAKE_WORD_THRESHOLD = 0.5

        # Detect on the 5th chunk
        fake_porc = _FakePorcupine(detect_on_chunks=[4])
        mock_pv.create.return_value = fake_porc

        from client.wake_word import WakeWordDetector
        detector = WakeWordDetector()

        chunk = _silence_chunk()
        for i in range(5):
            result = detector.process_chunk(chunk)
            if i < 4:
                self.assertFalse(result)
            else:
                self.assertTrue(result)

        detector.close()

    @patch("client.wake_word.pvporcupine")
    @patch("client.wake_word.settings")
    def test_chunk_size_matches_frame_length(self, mock_settings, mock_pv):
        mock_settings.PICOVOICE_ACCESS_KEY = "test-key"
        mock_settings.WAKE_WORD_KEYWORD = "porcupine"
        mock_settings.WAKE_WORD_KEYWORD_PATH = ""
        mock_settings.WAKE_WORD_THRESHOLD = 0.5

        fake_porc = _FakePorcupine()
        # Override frame_length to verify struct unpacking
        fake_porc.frame_length = 512
        mock_pv.create.return_value = fake_porc

        from client.wake_word import WakeWordDetector
        detector = WakeWordDetector()

        # Feed a properly-sized chunk (512 samples * 2 bytes = 1024 bytes)
        chunk = _silence_chunk(512)
        self.assertEqual(len(chunk), 1024)
        detector.process_chunk(chunk)  # should not raise

        detector.close()


class TestWakeWordInit(unittest.TestCase):
    """Test initialization validation."""

    @patch("client.wake_word.pvporcupine")
    @patch("client.wake_word.settings")
    def test_missing_access_key_raises(self, mock_settings, mock_pv):
        mock_settings.PICOVOICE_ACCESS_KEY = "  "
        mock_settings.WAKE_WORD_KEYWORD = "porcupine"
        mock_settings.WAKE_WORD_KEYWORD_PATH = ""

        from client.wake_word import WakeWordDetector
        with self.assertRaises(ValueError):
            WakeWordDetector()

    @patch("client.wake_word.pvporcupine")
    @patch("client.wake_word.settings")
    def test_empty_keyword_raises(self, mock_settings, mock_pv):
        mock_settings.PICOVOICE_ACCESS_KEY = "test-key"
        mock_settings.WAKE_WORD_KEYWORD = ""
        mock_settings.WAKE_WORD_KEYWORD_PATH = ""

        from client.wake_word import WakeWordDetector
        with self.assertRaises(ValueError):
            WakeWordDetector()


if __name__ == "__main__":
    unittest.main()
