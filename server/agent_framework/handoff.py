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
        from ..language import tr
        desc = self.description or tr(
            "handoff.default_description", agent=self.target_agent.name
        )
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": desc,
                "parameters": {"type": "object", "properties": {}},
            },
        }
