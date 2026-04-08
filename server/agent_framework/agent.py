"""Agent — declarative agent definition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Union

from .context import RunContext
from .guardrail import InputGuardrail, OutputGuardrail
from .handoff import Handoff
from .tool import FunctionTool

# instructions can be a static string or a callable that receives the RunContext
# (e.g. to inject the current time, user preferences, etc.)
Instructions = Union[str, Callable[[RunContext], str]]


@dataclass
class Agent:
    """Declarative agent definition (OpenAI Agents SDK style).

    Example::

        weather_agent = Agent(
            name="weather",
            instructions="你是一个天气查询助手。",
            tools=[get_weather_tool],
        )

        router = Agent(
            name="olivia",
            instructions=build_system_prompt,
            handoffs=[
                Handoff(target_agent=weather_agent, description="..."),
            ],
        )
    """

    name: str
    instructions: Instructions = "You are a helpful assistant."
    model: str | None = None  # None → use the global default from config
    tools: list[FunctionTool] = field(default_factory=list)
    handoffs: list[Handoff] = field(default_factory=list)
    input_guardrails: list[InputGuardrail] = field(default_factory=list)
    output_guardrails: list[OutputGuardrail] = field(default_factory=list)

    # ── helpers ────────────────────────────────────────────────────────────

    def resolve_instructions(self, ctx: RunContext) -> str:
        """Return the system prompt string, calling the function if needed."""
        if callable(self.instructions):
            return self.instructions(ctx)
        return self.instructions

    def all_tool_definitions(self) -> list[dict]:
        """Collect OpenAI-format definitions for all tools + handoffs."""
        defs = [t.definition for t in self.tools]
        for h in self.handoffs:
            defs.append(h.as_tool_definition())
        return defs

    def get_tool(self, name: str) -> FunctionTool | None:
        """Look up a tool by name."""
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def get_handoff(self, tool_name: str) -> Handoff | None:
        """Look up a handoff by its auto-generated tool name."""
        for h in self.handoffs:
            if h.tool_name == tool_name:
                return h
        return None
