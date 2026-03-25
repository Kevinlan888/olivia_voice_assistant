import io
import logging
import edge_tts
from .base import BaseTTS
from ..config import settings

logger = logging.getLogger(__name__)


class EdgeTTSEngine(BaseTTS):
    """Async TTS using Microsoft Edge TTS (edge-tts library).
    
    Free, no API key required. Produces MP3 bytes directly.
    Supports 300+ voices: https://github.com/rany2/edge-tts
    """

    def __init__(self):
        self._voice = settings.EDGE_TTS_VOICE
        logger.info("Edge-TTS ready: voice=%s", self._voice)

    async def synthesize(self, text: str) -> bytes:
        """Convert text to MP3 bytes using Edge TTS."""
        communicate = edge_tts.Communicate(text, self._voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()
