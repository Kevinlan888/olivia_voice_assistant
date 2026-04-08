"""
Event types and EventEmitter for the agent framework.

All events are plain dataclasses that the Runner emits during execution.
Consumers (WebSocket handler, tracing, logging) subscribe via EventEmitter.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Union


# ── Event types ───────────────────────────────────────────────────────────────

@dataclass
class AgentStart:
    agent_name: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class AgentEnd:
    agent_name: str
    output: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class LLMStart:
    model: str | None = None
    timestamp: float = field(default_factory=time.time)

@dataclass
class LLMEnd:
    content: str = ""
    tool_calls: list[dict] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class LLMTokenDelta:
    """A single token from streaming LLM output."""
    token: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class ToolCallStart:
    tool_name: str
    arguments: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

@dataclass
class ToolCallEnd:
    tool_name: str
    result: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class HandoffEvent:
    from_agent: str
    to_agent: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class StatusMessage:
    """Human-readable status text (e.g. "正在查询天气...")."""
    text: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class GuardrailTriggered:
    guardrail_name: str
    message: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class RunError:
    error: str
    timestamp: float = field(default_factory=time.time)


# Union of all event types
Event = Union[
    AgentStart, AgentEnd,
    LLMStart, LLMEnd, LLMTokenDelta,
    ToolCallStart, ToolCallEnd,
    HandoffEvent,
    StatusMessage,
    GuardrailTriggered,
    RunError,
]


# ── EventEmitter ──────────────────────────────────────────────────────────────

# Listener signature: receives any Event
Listener = Callable[[Event], Awaitable[None]]


class EventEmitter:
    """Simple async event bus — listeners receive every emitted event."""

    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def on(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def off(self, listener: Listener) -> None:
        self._listeners = [l for l in self._listeners if l is not listener]

    async def emit(self, event: Event) -> None:
        for listener in self._listeners:
            await listener(event)
