"""RunContext — shared state bag passed to every agent, tool, and guardrail."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..token_counter import count_messages_tokens

if TYPE_CHECKING:
    from ..llm.base import BaseLLM

logger = logging.getLogger(__name__)



@dataclass
class RunContext:
    """Mutable context shared across a single agent-run invocation.

    Every tool function, guardrail, and dynamic-instructions callable receives
    the *same* ``RunContext`` instance so they can read/write shared state.
    """

    # Unique identifier for this conversation session.
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # Conversation history (list of OpenAI-format message dicts).
    # The Runner will prepend the system prompt; callers only need to
    # supply user/assistant turns.
    history: list[dict] = field(default_factory=list)

    # Rolling summary of conversation turns that have been evicted from
    # the history to stay within the token budget.
    summary: str = ""

    # Timezone-aware "now" snapshot, set once at the start of a run.
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc).astimezone())

    # Free-form metadata bucket — tools / guardrails can stash data here.
    metadata: dict = field(default_factory=dict)

    # ── helpers ────────────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, **extra: object) -> None:
        msg: dict = {"role": role, "content": content, **extra}
        self.history.append(msg)

    async def compact(
        self,
        max_tokens: int,
        llm: BaseLLM,
        *,
        enable_summary: bool = True,
    ) -> None:
        """Evict oldest messages until history fits within *max_tokens*.

        When *enable_summary* is True the evicted messages are summarised by
        the LLM and stored in ``self.summary`` so context is not entirely lost.
        """
        current = count_messages_tokens(self.history)
        target = int(max_tokens * 0.75)  # keep 25 % headroom

        if current <= max_tokens:
            return

        # Collect messages to evict (oldest first)
        evicted: list[dict] = []
        while self.history and count_messages_tokens(self.history) > target:
            evicted.append(self.history.pop(0))

        if not evicted:
            return

        logger.info(
            "[Context] compacted: evicted %d msgs (%d → %d tokens)",
            len(evicted),
            current,
            count_messages_tokens(self.history),
        )

        if enable_summary:
            await self._update_summary(evicted, llm)

    async def _update_summary(self, evicted: list[dict], llm: BaseLLM) -> None:
        """Generate a rolling summary from evicted messages + prior summary."""
        from ..language import tr
        parts: list[str] = []
        if self.summary:
            parts.append(f"[之前的摘要]\n{self.summary}\n")
        parts.append("尚未了解过去的对话\n")
        for msg in evicted:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if content:
                parts.append(f"{role}: {content}")

        prompt_text = tr("context.summary_prompt") + "\n".join(parts)
        try:
            self.summary = await llm.generate(
                [{"role": "user", "content": prompt_text}]
            )
            logger.info("[Context] summary updated (%d chars)", len(self.summary))
        except Exception:
            logger.exception("[Context] summary generation failed, keeping old summary")

    def build_messages(self, system_prompt: str) -> list[dict]:
        """Return a full message list with the system prompt prepended."""
        msgs = [{"role": "system", "content": system_prompt}]
        if self.summary:
            msgs.append({
                "role": "system",
                "content": f"[Prior conversation summary]\n{self.summary}",
            })
        msgs.extend(self.history)
        return msgs
