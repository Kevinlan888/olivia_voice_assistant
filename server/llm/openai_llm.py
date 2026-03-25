import logging
from openai import AsyncOpenAI
from .base import BaseLLM
from ..config import settings

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """Async LLM client using the OpenAI Chat Completions API.

    Compatible with any OpenAI-compatible endpoint (OpenAI, Azure, local vLLM, etc.)
    by overriding OPENAI_BASE_URL in the .env file.
    """

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        self._model = settings.OPENAI_MODEL
        logger.info("OpenAI LLM ready: model=%s base_url=%s", self._model, settings.OPENAI_BASE_URL)

    async def generate(self, messages: list[dict]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()

    async def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call the API with tool definitions; normalise the response."""
        kwargs: dict = dict(
            model=self._model,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        # Normalise tool_calls to plain dicts for easy JSON handling
        raw_calls = msg.tool_calls or []
        tool_calls = [
            {
                "id": tc.id,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in raw_calls
        ] if raw_calls else None

        return {"content": msg.content or "", "tool_calls": tool_calls}
