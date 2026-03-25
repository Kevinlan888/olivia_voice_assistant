from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BaseTTS(ABC):
    @abstractmethod
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield synthesized audio chunks progressively."""

    async def synthesize(self, text: str) -> bytes:
        """Convert text to a single audio blob by collecting stream chunks."""
        chunks: list[bytes] = []
        async for chunk in self.synthesize_stream(text):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
