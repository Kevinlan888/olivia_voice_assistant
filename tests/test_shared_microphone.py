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

    def __init__(
        self,
        stream: _FakeStream,
        devices: list[dict] | None = None,
        has_default_input: bool = True,
    ):
        self._stream = stream
        self._devices = devices or [
            {"index": 0, "name": "default mic", "maxInputChannels": 1}
        ]
        self._default_input_device: dict | None = None
        if has_default_input:
            self._default_input_device = next(
                (device for device in self._devices if device.get("maxInputChannels", 0) > 0),
                None,
            )
        self.open_calls: list[dict] = []

    def open(self, **kwargs):
        self.open_calls.append(kwargs)
        return self._stream

    def get_default_input_device_info(self):
        if self._default_input_device is None:
            raise OSError("no default input device")
        return self._default_input_device

    def get_device_count(self):
        return len(self._devices)

    def get_device_info_by_index(self, index: int):
        return self._devices[index]

    def terminate(self):
        pass


class TestSharedMicrophoneRead(unittest.TestCase):
    """Test basic chunk reading."""

    @patch("client.shared_microphone.manager")
    def test_read_returns_chunks(self, mock_manager):
        chunks = [_noise_chunk(), _silence_chunk(), _noise_chunk()]
        fake_stream = _FakeStream(chunks)
        mock_manager.fresh_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        result = mic.read_chunk()
        self.assertEqual(result, chunks[0])
        mic.close()

    @patch("client.shared_microphone.manager")
    def test_iterator_protocol(self, mock_manager):
        chunks = [_noise_chunk(), _silence_chunk()]
        fake_stream = _FakeStream(chunks)
        mock_manager.fresh_pa.return_value = _FakePA(fake_stream)

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
        mock_manager.fresh_pa.return_value = _FakePA(fake_stream)

        mic = SharedMicrophone()
        mic.close()
        self.assertTrue(fake_stream.stopped)
        self.assertTrue(fake_stream.closed)

    @patch("client.shared_microphone.manager")
    def test_read_after_close_raises_stop_iteration(self, mock_manager):
        fake_stream = _FakeStream([_silence_chunk()])
        mock_manager.fresh_pa.return_value = _FakePA(fake_stream)

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
        mock_manager.fresh_pa.return_value = _FakePA(fake_stream)

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
        initial_fake_pa = _FakePA(fake_stream)
        mock_manager.fresh_pa.side_effect = [initial_fake_pa, new_fake_pa]

        mic = SharedMicrophone()
        for _ in range(5):
            result = mic.read_chunk()
            self.assertEqual(result, _silence_chunk())  # silence on error

        # The 5th error should have triggered recreation
        self.assertEqual(mock_manager.fresh_pa.call_count, 2)
        mic.close()


class TestSharedMicrophoneStartup(unittest.TestCase):
    """Test startup failure behavior."""

    @patch("client.shared_microphone.manager")
    def test_startup_failure_raises(self, mock_manager):
        """If PyAudio.open fails at init, the constructor raises."""
        fake_pa = _FakePA(_FakeStream([]))
        fake_pa.open = MagicMock(side_effect=OSError("device busy"))
        mock_manager.fresh_pa.return_value = fake_pa

        with self.assertRaises(OSError):
            SharedMicrophone()

    @patch("client.shared_microphone.manager")
    def test_startup_uses_first_input_device_when_no_default_exists(self, mock_manager):
        """Startup falls back to the first input-capable device."""
        fake_pa = _FakePA(
            _FakeStream([_silence_chunk()]),
            devices=[
                {"index": 0, "name": "speaker", "maxInputChannels": 0},
                {"index": 3, "name": "usb mic", "maxInputChannels": 1},
            ],
            has_default_input=False,
        )
        mock_manager.fresh_pa.return_value = fake_pa

        mic = SharedMicrophone()

        self.assertEqual(fake_pa.open_calls[0]["input_device_index"], 3)
        mic.close()


if __name__ == "__main__":
    unittest.main()
