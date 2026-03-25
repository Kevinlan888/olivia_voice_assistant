from abc import ABC, abstractmethod


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
