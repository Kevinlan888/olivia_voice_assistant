"""Handoff — delegate control from one agent to another."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .tool import FunctionTool

if TYPE_CHECKING:
    from .agent import Agent


@dataclass(frozen=True)
class Handoff:
    """Describes a delegation target that the LLM can invoke as a tool.

    When the LLM calls the auto-generated ``transfer_to_<agent_name>`` tool,
    the Runner switches execution to ``target_agent`` while preserving the
    shared :class:`RunContext`.
    """

    target_agent: Agent
    description: str = ""

    @property
    def tool_name(self) -> str:
        return f"transfer_to_{self.target_agent.name}"

    def as_tool_definition(self) -> dict:
        """Generate an OpenAI-format tool definition for the handoff."""
        desc = self.description or (
            f"将对话转交给 {self.target_agent.name} 处理。"
            f"当你认为 {self.target_agent.name} 更适合回答当前问题时调用此工具。"
        )
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": desc,
                "parameters": {"type": "object", "properties": {}},
            },
        }
