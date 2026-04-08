"""
WebSocket protocol v2 — event-based JSON frames.

v2 events are JSON text frames. Binary frames remain MP3 audio chunks.
Protocol negotiation: client sends ``{"protocol": "v2"}`` as the first
text frame after connection. If not received, the server falls back to
v1 (plain-text ``STATUS:``, ``DONE``, ``ASSISTANT_TEXT:`` frames).
"""

from __future__ import annotations

import json
from typing import Any

from .agent_framework import events as ev


# ── v2 event serialization ────────────────────────────────────────────────────

def event_to_v2(event: ev.Event) -> str | None:
    """Serialize a framework event to a v2 JSON text frame.

    Returns None for events that don't need a wire representation.
    """
    if isinstance(event, ev.AgentStart):
        return _json(event="agent_start", agent=event.agent_name)
    if isinstance(event, ev.AgentEnd):
        return _json(event="agent_end", agent=event.agent_name)
    if isinstance(event, ev.LLMTokenDelta):
        return _json(event="llm_token", token=event.token)
    if isinstance(event, ev.ToolCallStart):
        return _json(event="tool_start", tool=event.tool_name, args=event.arguments)
    if isinstance(event, ev.ToolCallEnd):
        return _json(event="tool_end", tool=event.tool_name, result=event.result)
    if isinstance(event, ev.HandoffEvent):
        return _json(event="handoff", **{"from": event.from_agent, "to": event.to_agent})
    if isinstance(event, ev.StatusMessage):
        return _json(event="status", text=event.text)
    if isinstance(event, ev.GuardrailTriggered):
        return _json(event="guardrail", name=event.guardrail_name, message=event.message)
    if isinstance(event, ev.RunError):
        return _json(event="error", message=event.error)
    return None


# ── v1 compatibility layer ────────────────────────────────────────────────────

def event_to_v1(event: ev.Event) -> str | None:
    """Serialize a framework event to a v1 plain-text frame.

    v1 only supports a subset of events.
    """
    if isinstance(event, ev.StatusMessage):
        return f"STATUS:{event.text}"
    if isinstance(event, ev.RunError):
        return f"ERROR:{event.error}"
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(**data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def is_v2_handshake(text: str) -> bool:
    """Check if a text frame is a v2 protocol handshake."""
    try:
        data = json.loads(text)
        return data.get("protocol") == "v2"
    except (json.JSONDecodeError, AttributeError):
        return False
