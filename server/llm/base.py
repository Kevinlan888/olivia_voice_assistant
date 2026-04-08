from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class StreamDelta:
    """A single chunk from a streaming LLM response.

    Attributes:
        token:        Text fragment (may be empty during tool-call deltas).
        tool_calls_delta: Incremental tool-call data (OpenAI streaming format).
        finish_reason: "stop", "tool_calls", or None while still streaming.
    """
    token: str = ""
    tool_calls_delta: list[dict] | None = None
    finish_reason: str | None = None


class BaseLLM(ABC):
    @abstractmethod
    async def generate(self, messages: list[dict]) -> str:
        """Given a list of chat messages, return the assistant's reply."""

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """
        Run a chat completion that may return tool calls.

        Returns a dict with:
            content   (str | None)  — assistant text, if any
            tool_calls (list | None) — list of tool call dicts, if any

        Each tool_call has the shape:
            {
                "id":       str,
                "function": {"name": str, "arguments": str (JSON)},
            }
        """

    async def generate_stream(
        self,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream text tokens. Default falls back to non-streaming."""
        result = await self.generate(messages)
        yield result

    async def generate_with_tools_stream(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[StreamDelta]:
        """Stream deltas that may contain text tokens or tool-call fragments.

        Default falls back to a single non-streaming response.
        """
        response = await self.generate_with_tools(messages, tools)
        yield StreamDelta(
            token=response.get("content", ""),
            finish_reason="tool_calls" if response.get("tool_calls") else "stop",
            tool_calls_delta=response.get("tool_calls"),
        )
