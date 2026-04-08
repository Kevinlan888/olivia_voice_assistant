"""Input and output guardrails for the agent framework."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .context import RunContext


@dataclass
class GuardrailResult:
    """Outcome of a guardrail check."""
    passed: bool
    reject_message: str | None = None


class InputGuardrail(ABC):
    """Checks user input *before* the LLM is called.

    Input guardrails run in parallel with each other (and optionally in
    parallel with the LLM call) to minimize added latency.
    """

    name: str = "input_guardrail"

    @abstractmethod
    async def check(self, ctx: RunContext, user_input: str) -> GuardrailResult:
        ...


class OutputGuardrail(ABC):
    """Checks assistant output *after* the LLM produces a final reply.

    If the guardrail rejects the output, the Runner replaces the reply
    with ``reject_message``.
    """

    name: str = "output_guardrail"

    @abstractmethod
    async def check(self, ctx: RunContext, output: str) -> GuardrailResult:
        ...


# ── Built-in guardrails ──────────────────────────────────────────────────────

class MaxTokensInputGuardrail(InputGuardrail):
    """Reject user input that exceeds a character limit."""

    name = "max_tokens_input"

    def __init__(self, max_chars: int = 2000):
        self.max_chars = max_chars

    async def check(self, ctx: RunContext, user_input: str) -> GuardrailResult:
        if len(user_input) > self.max_chars:
            return GuardrailResult(
                passed=False,
                reject_message=f"输入过长（{len(user_input)} 字符，上限 {self.max_chars}），请精简后重试。",
            )
        return GuardrailResult(passed=True)
