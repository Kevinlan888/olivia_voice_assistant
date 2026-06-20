import asyncio
import sys
import types
import unittest

sys.modules.setdefault("pyaudio", types.SimpleNamespace(paInt16=8, paContinue=0, PyAudio=object))
sys.modules.setdefault("pvporcupine", types.SimpleNamespace(create=lambda *args, **kwargs: object()))
sys.modules.setdefault("client.silero_vad", types.SimpleNamespace(SileroVAD=object))
sys.modules.setdefault(
    "websockets",
    types.SimpleNamespace(connect=lambda *args, **kwargs: None),
)
sys.modules.setdefault(
    "websockets.exceptions",
    types.SimpleNamespace(ConnectionClosedError=Exception),
)
sys.modules.setdefault(
    "miniaudio",
    types.SimpleNamespace(
        SampleFormat=types.SimpleNamespace(SIGNED16="SIGNED16"),
        decode=lambda *args, **kwargs: types.SimpleNamespace(samples=b"pcm"),
    ),
)

from client.main import _request_shutdown


class TestShutdownSignal(unittest.TestCase):
    def test_request_shutdown_sets_event_and_cancels_task(self):
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)

        stop_event = asyncio.Event()

        class _FakeTask:
            def __init__(self):
                self.cancel_called = False

            def done(self):
                return False

            def cancel(self):
                self.cancel_called = True

        task = _FakeTask()

        _request_shutdown(stop_event, task, loop)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(task.cancel_called)


if __name__ == "__main__":
    unittest.main()
