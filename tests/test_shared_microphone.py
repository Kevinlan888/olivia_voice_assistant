"""Unit tests for SharedMicrophone.

Uses a fake PyAudio stream to avoid real hardware dependency.
"""

import struct
import unittest
from unittest.mock import MagicMock, patch

from client.shared_microphone import SharedMicrophone


def _silence_chunk(frame_length: int = 512) -> bytes:
    """Return a chunk of all-zero int16 samples."""
    return b"\x00" * (frame_length * 2)


def _noise_chunk(frame_length: int = 512) -> bytes:
    """Return a chunk of non-zero int16 samples."""
    return struct.pack(f"{frame_length}h", *([100] * frame_length))


class _FakeStream:
    """Mimics a PyAudio stream with a pre-loaded sequence of chunks."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self._idx = 0
        self.stopped = False
        self.closed = False

    def read(self, frames, exception_on_overflow=False):
        if self._idx >= len(self._chunks):
            raise StopIteration("no more chunks")
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakePA:
    """Mimics pyaudio.PyAudio with a fake stream."""

    def __init__(self, stream: _FakeStream):
        self._stream = stream

    def open(self, **kwargs):
        return self._stream

    def terminate(self):
        pass


class TestSharedMicrophoneRead(unittest.TestCase):
    """Test basic chunk reading."""

    @patch("client.shared_microphone.manager")
    def test_read_returns_chunks(self, mock_manager):
        chunks = [_noise_chunk(), _silence_chunk(), _noise_chunk()]
        fake_stream = _FakeStream(chunks)
        mock_manager.get_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        result = mic.read_chunk()
        self.assertEqual(result, chunks[0])
        mic.close()

    @patch("client.shared_microphone.manager")
    def test_iterator_protocol(self, mock_manager):
        chunks = [_noise_chunk(), _silence_chunk()]
        fake_stream = _FakeStream(chunks)
        mock_manager.get_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        collected = []
        for i, chunk in enumerate(mic):
            collected.append(chunk)
            if i >= 1:
                break
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0], chunks[0])
        self.assertEqual(collected[1], chunks[1])
        mic.close()


class TestSharedMicrophoneClose(unittest.TestCase):
    """Test clean shutdown."""

    @patch("client.shared_microphone.manager")
    def test_close_stops_and_closes_stream(self, mock_manager):
        fake_stream = _FakeStream([_silence_chunk()])
        mock_manager.get_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        mic.close()
        self.assertTrue(fake_stream.stopped)
        self.assertTrue(fake_stream.closed)

    @patch("client.shared_microphone.manager")
    def test_read_after_close_raises_stop_iteration(self, mock_manager):
        fake_stream = _FakeStream([_silence_chunk()])
        mock_manager.get_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        mic.close()
        with self.assertRaises(StopIteration):
            mic.read_chunk()


class TestSharedMicrophoneErrorRecovery(unittest.TestCase):
    """Test transient read error handling."""

    @patch("client.shared_microphone.manager")
    def test_transient_error_returns_silence(self, mock_manager):
        """A single read error returns a silence chunk, not an exception."""
        fake_stream = _FakeStream([_silence_chunk()])
        fake_stream.read = MagicMock(
            side_effect=[OSError("read error"), _noise_chunk()]
        )
        mock_manager.get_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        result = mic.read_chunk()
        self.assertEqual(result, _silence_chunk())

        # Next read should work normally
        result2 = mic.read_chunk()
        self.assertEqual(result2, _noise_chunk())
        mic.close()

    @patch("client.shared_microphone.manager")
    def test_repeated_errors_trigger_recreate(self, mock_manager):
        """After MAX_CONSECUTIVE_ERRORS, stream recreation is attempted."""
        fake_stream = _FakeStream([_silence_chunk()])
        # First 5 reads fail, then succeed on recreated stream
        fake_stream.read = MagicMock(side_effect=[OSError("err")] * 5 + [_noise_chunk()])
        new_fake_stream = _FakeStream([_noise_chunk()])
        new_fake_pa = _FakePA(new_fake_stream)
        mock_manager.get_pa.return_value = _FakePA(fake_stream)
        mock_manager.fresh_pa.return_value = new_fake_pa

        mic = SharedMicrophone()
        for _ in range(5):
            result = mic.read_chunk()
            self.assertEqual(result, _silence_chunk())  # silence on error

        # The 5th error should have triggered recreation
        mock_manager.fresh_pa.assert_called_once()
        mic.close()


class TestSharedMicrophoneStartup(unittest.TestCase):
    """Test startup failure behavior."""

    @patch("client.shared_microphone.manager")
    def test_startup_failure_raises(self, mock_manager):
        """If PyAudio.open fails at init, the constructor raises."""
        fake_pa = _FakePA(_FakeStream([]))
        fake_pa.open = MagicMock(side_effect=OSError("device busy"))
        mock_manager.get_pa.return_value = fake_pa

        with self.assertRaises(OSError):
            SharedMicrophone()


if __name__ == "__main__":
    unittest.main()
