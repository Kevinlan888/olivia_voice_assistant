from abc import ABC, abstractmethod


class BaseTTS(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (MP3 or WAV)."""
