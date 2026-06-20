import asyncio
import unittest


class TestStreamingUploadBridge(unittest.IsolatedAsyncioTestCase):
    async def test_queue_bridge_preserves_chunk_order(self):
        sent: list[bytes] = []
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        async def fake_send_audio_chunk(chunk: bytes) -> None:
            sent.append(chunk)

        async def flush_queue() -> None:
            while not queue.empty():
                await fake_send_audio_chunk(await queue.get())

        await queue.put(b"chunk-1")
        await queue.put(b"chunk-2")
        await flush_queue()

        self.assertEqual(sent, [b"chunk-1", b"chunk-2"])


if __name__ == "__main__":
    unittest.main()
