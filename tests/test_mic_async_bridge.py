import asyncio
import unittest


class TestMicAsyncBridge(unittest.IsolatedAsyncioTestCase):
    async def test_async_read_delegates_to_thread(self):
        calls: list[str] = []

        class _FakeMic:
            def read_chunk(self):
                calls.append("read")
                return b"chunk"

        mic = _FakeMic()

        result = await asyncio.to_thread(mic.read_chunk)

        self.assertEqual(result, b"chunk")
        self.assertEqual(calls, ["read"])


if __name__ == "__main__":
    unittest.main()
