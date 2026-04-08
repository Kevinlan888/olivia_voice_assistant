"""RunContext — shared state bag passed to every agent, tool, and guardrail."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


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

    # Timezone-aware "now" snapshot, set once at the start of a run.
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc).astimezone())

    # Free-form metadata bucket — tools / guardrails can stash data here.
    metadata: dict = field(default_factory=dict)

    # ── helpers ────────────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, **extra: object) -> None:
        msg: dict = {"role": role, "content": content, **extra}
        self.history.append(msg)

    def trim_history(self, max_turns: int) -> None:
        """Keep only the last *max_turns* user/assistant pairs."""
        max_msgs = max_turns * 2
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]

    def build_messages(self, system_prompt: str) -> list[dict]:
        """Return a full message list with the system prompt prepended."""
        return [{"role": "system", "content": system_prompt}] + list(self.history)
