import json
import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .base import BaseLLM, StreamDelta
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

    # ── Streaming methods ─────────────────────────────────────────────────

    async def generate_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def generate_with_tools_stream(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[StreamDelta]:
        kwargs: dict = dict(
            model=self._model,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = await self._client.chat.completions.create(**kwargs)

        # Accumulate tool call fragments across chunks
        tool_calls_accum: dict[int, dict] = {}  # index → {id, function: {name, arguments}}

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            finish = choice.finish_reason

            # Text token
            token = delta.content or "" if delta else ""

            # Tool call deltas
            tc_delta = None
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_accum:
                        tool_calls_accum[idx] = {
                            "id": tc.id or "",
                            "function": {"name": tc.function.name or "", "arguments": ""},
                        }
                    else:
                        if tc.id:
                            tool_calls_accum[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_accum[idx]["function"]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments

            # Emit delta
            if finish == "tool_calls":
                tc_delta = list(tool_calls_accum.values()) if tool_calls_accum else None
                yield StreamDelta(token=token, tool_calls_delta=tc_delta, finish_reason="tool_calls")
            elif finish == "stop":
                yield StreamDelta(token=token, finish_reason="stop")
            elif token:
                yield StreamDelta(token=token)
