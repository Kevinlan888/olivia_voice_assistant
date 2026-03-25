import logging
from collections.abc import AsyncIterator

import httpx
from .base import BaseTTS
from ..config import settings

logger = logging.getLogger(__name__)


class SovitsTTS(BaseTTS):
    """Async TTS using a locally running GPT-SoVITS API server.
    
    Assumes GPT-SoVITS is running at SOVITS_BASE_URL and exposes
    a /tts endpoint that returns WAV audio.
    
    Adjust the payload fields to match your GPT-SoVITS API version.
    Reference: https://github.com/RVC-Boss/GPT-SoVITS
    """

    def __init__(self):
        self._base_url = settings.SOVITS_BASE_URL.rstrip("/")
        self._http = httpx.AsyncClient(timeout=60.0)
        logger.info("GPT-SoVITS TTS ready: url=%s", self._base_url)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield TTS audio chunks (single chunk fallback for current SoVITS API)."""
        yield await self.synthesize(text)

    async def synthesize(self, text: str) -> bytes:
        """POST text to GPT-SoVITS and return raw WAV bytes."""
        payload = {
            "text": text,
            "text_lang": "zh",          # adjust as needed
            "ref_audio_path": "",       # set your reference audio path
            "prompt_lang": "zh",
            "prompt_text": "",
            "text_split_method": "cut5",
            "batch_size": 1,
            "streaming_mode": False,
            "media_type": "wav",
        }
        response = await self._http.post(f"{self._base_url}/tts", json=payload)
        response.raise_for_status()
        return response.content
