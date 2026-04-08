"""Span-based tracing for the agent framework.

Collects structured traces via EventEmitter events, then exports them
as JSON logs (with a pluggable TraceExporter for future OpenTelemetry support).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from . import events as ev

logger = logging.getLogger(__name__)


# ── Span types ────────────────────────────────────────────────────────────────

@dataclass
class Span:
    span_type: str
    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[Span] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class Trace:
    """A top-level trace encompassing one full agent-run invocation."""
    trace_id: str = ""
    spans: list[Span] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str, **kwargs)


# ── Trace Exporter protocol ──────────────────────────────────────────────────

class TraceExporter(Protocol):
    async def export(self, trace: Trace) -> None: ...


class LogTraceExporter:
    """Exports traces as JSON to the Python logger."""

    def __init__(self, logger_name: str = "olivia.tracing"):
        self._logger = logging.getLogger(logger_name)

    async def export(self, trace: Trace) -> None:
        self._logger.info(
            "[Trace %s] %d spans, %.0fms\n%s",
            trace.trace_id,
            len(trace.spans),
            trace.duration_ms,
            trace.to_json(indent=2),
        )


# ── TraceCollector — listens to events and builds a Trace ─────────────────────

class TraceCollector:
    """Subscribe to an EventEmitter, accumulate spans, and export on completion.

    Usage::

        collector = TraceCollector(trace_id="abc", exporter=LogTraceExporter())
        emitter.on(collector.handle_event)
        # ... run agent ...
        await collector.finalize()
    """

    def __init__(
        self,
        trace_id: str = "",
        exporter: TraceExporter | None = None,
    ):
        self._trace = Trace(trace_id=trace_id, start_time=time.time())
        self._exporter = exporter or LogTraceExporter()
        self._current_agent_span: Span | None = None
        self._current_llm_span: Span | None = None
        self._tool_spans: dict[str, Span] = {}  # keyed by tool_name

    async def handle_event(self, event: ev.Event) -> None:
        if isinstance(event, ev.AgentStart):
            span = Span(span_type="agent", name=event.agent_name, start_time=event.timestamp)
            self._current_agent_span = span
            self._trace.spans.append(span)

        elif isinstance(event, ev.AgentEnd):
            if self._current_agent_span:
                self._current_agent_span.end_time = event.timestamp
                self._current_agent_span.attributes["output_preview"] = event.output[:200]
                self._current_agent_span = None

        elif isinstance(event, ev.LLMStart):
            span = Span(
                span_type="llm",
                name=event.model or "unknown",
                start_time=event.timestamp,
            )
            self._current_llm_span = span
            parent = self._current_agent_span or self._trace
            if isinstance(parent, Span):
                parent.children.append(span)
            else:
                parent.spans.append(span)

        elif isinstance(event, ev.LLMEnd):
            if self._current_llm_span:
                self._current_llm_span.end_time = event.timestamp
                self._current_llm_span.attributes.update({
                    "tokens_in": event.tokens_in,
                    "tokens_out": event.tokens_out,
                    "duration_ms": event.duration_ms,
                    "has_tool_calls": bool(event.tool_calls),
                })
                self._current_llm_span = None

        elif isinstance(event, ev.ToolCallStart):
            span = Span(
                span_type="tool",
                name=event.tool_name,
                start_time=event.timestamp,
                attributes={"arguments": event.arguments},
            )
            self._tool_spans[event.tool_name] = span
            parent = self._current_agent_span
            if parent:
                parent.children.append(span)
            else:
                self._trace.spans.append(span)

        elif isinstance(event, ev.ToolCallEnd):
            span = self._tool_spans.pop(event.tool_name, None)
            if span:
                span.end_time = event.timestamp
                span.attributes["duration_ms"] = event.duration_ms
                span.attributes["result_preview"] = event.result[:200]

        elif isinstance(event, ev.HandoffEvent):
            if self._current_agent_span:
                self._current_agent_span.attributes["handoff_to"] = event.to_agent

        elif isinstance(event, ev.GuardrailTriggered):
            span = Span(
                span_type="guardrail",
                name=event.guardrail_name,
                start_time=event.timestamp,
                end_time=event.timestamp,
                attributes={"message": event.message},
            )
            self._trace.spans.append(span)

    async def finalize(self) -> Trace:
        """Mark trace complete and export."""
        self._trace.end_time = time.time()
        await self._exporter.export(self._trace)
        return self._trace
