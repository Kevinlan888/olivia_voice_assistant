"""
Runner — core orchestrator for agent execution.

Drives the tool-calling loop, handles handoffs between agents,
runs guardrails, and emits events for tracing / WebSocket streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .agent import Agent
from .context import RunContext
from .events import (
    AgentEnd,
    AgentStart,
    Event,
    EventEmitter,
    GuardrailTriggered,
    HandoffEvent,
    LLMEnd,
    LLMStart,
    LLMTokenDelta,
    RunError,
    StatusMessage,
    ToolCallEnd,
    ToolCallStart,
)
from .guardrail import GuardrailResult
from .tool import FunctionTool
from .tracing import LogTraceExporter, TraceCollector
from ..language import tr

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


@dataclass
class RunResult:
    """Final output of a Runner.run() invocation."""
    output: str
    agent_name: str
    context: RunContext


class Runner:
    """Executes an agent loop: LLM → tools/handoffs → repeat.

    Usage (non-streaming)::

        runner = Runner(llm_client=llm, emitter=emitter)
        result = await runner.run(agent, context)

    Usage (streaming)::

        async for event in runner.run_stream(agent, context):
            if isinstance(event, LLMTokenDelta):
                ...  # feed to sentence splitter / TTS
    """

    def __init__(
        self,
        llm_client: Any,
        emitter: EventEmitter | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        enable_tracing: bool = True,
        streaming: bool = True,
    ):
        self._llm = llm_client
        self._emitter = emitter or EventEmitter()
        self._max_rounds = max_tool_rounds
        self._enable_tracing = enable_tracing
        self._streaming = streaming

    # ── Public: non-streaming run ─────────────────────────────────────────

    async def run(self, agent: Agent, ctx: RunContext) -> RunResult:
        """Drive the agentic loop until a final text reply is produced."""
        trace_id = uuid.uuid4().hex[:12]
        collector: TraceCollector | None = None
        if self._enable_tracing:
            collector = TraceCollector(trace_id=trace_id, exporter=LogTraceExporter())
            self._emitter.on(collector.handle_event)

        try:
            result = await self._run_agent_loop(agent, ctx)
        finally:
            if collector:
                self._emitter.off(collector.handle_event)
                await collector.finalize()

        return result

    # ── Public: streaming run ─────────────────────────────────────────────

    async def run_stream(self, agent: Agent, ctx: RunContext) -> AsyncIterator[Event]:
        """Drive the agentic loop, yielding events as they happen.

        Callers can feed ``LLMTokenDelta`` events into a sentence splitter
        for progressive TTS synthesis.
        """
        trace_id = uuid.uuid4().hex[:12]
        collector: TraceCollector | None = None
        if self._enable_tracing:
            collector = TraceCollector(trace_id=trace_id, exporter=LogTraceExporter())
            self._emitter.on(collector.handle_event)

        # Replace the emitter with a queue-based one so we can yield events
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        original_emitter = self._emitter

        async def _queue_listener(event: Event) -> None:
            await queue.put(event)

        original_emitter.on(_queue_listener)

        async def _producer():
            try:
                await self._run_agent_loop(agent, ctx)
            except Exception as exc:
                await original_emitter.emit(RunError(error=str(exc)))
            finally:
                await queue.put(None)  # sentinel

        task = asyncio.create_task(_producer())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            original_emitter.off(_queue_listener)
            if collector:
                original_emitter.off(collector.handle_event)
                await collector.finalize()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # ── Core loop ─────────────────────────────────────────────────────────

    async def _run_agent_loop(self, agent: Agent, ctx: RunContext) -> RunResult:
        current_agent = agent

        await self._emitter.emit(AgentStart(agent_name=current_agent.name))

        # Run input guardrails
        user_input = self._last_user_message(ctx)
        guardrail_rejection = await self._run_input_guardrails(current_agent, ctx, user_input)
        if guardrail_rejection:
            await self._emitter.emit(AgentEnd(agent_name=current_agent.name, output=guardrail_rejection))
            return RunResult(output=guardrail_rejection, agent_name=current_agent.name, context=ctx)

        # Build initial messages
        system_prompt = current_agent.resolve_instructions(ctx)
        msgs = ctx.build_messages(system_prompt)

        for round_num in range(1, self._max_rounds + 1):
            logger.info("[Runner] agent=%s round=%d msgs=%d", current_agent.name, round_num, len(msgs))

            # Call LLM
            tool_defs = current_agent.all_tool_definitions()
            t0 = time.time()
            await self._emitter.emit(LLMStart(model=current_agent.model))

            logger.info("[Runner] calling LLM, msg: %s", msgs[-1] if msgs else "[]")
            response = await self._call_llm(msgs, tool_defs)

            duration = (time.time() - t0) * 1000
            await self._emitter.emit(LLMEnd(
                content=response.get("content", ""),
                tool_calls=response.get("tool_calls"),
                duration_ms=duration,
            ))

            # No tool calls → final reply
            if not response.get("tool_calls"):
                reply = (response.get("content") or "").strip()

                # Output guardrails
                guardrail_result = await self._run_output_guardrails(current_agent, ctx, reply)
                if guardrail_result:
                    reply = guardrail_result

                await self._emitter.emit(AgentEnd(agent_name=current_agent.name, output=reply))
                return RunResult(output=reply, agent_name=current_agent.name, context=ctx)

            # Process tool calls
            tool_calls = response["tool_calls"]
            logger.info("[Runner] %d tool call(s) requested", len(tool_calls))

            # Append the assistant's tool-calling turn
            msgs.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            })

            # Check for handoffs first
            handoff_target = self._find_handoff(current_agent, tool_calls)
            if handoff_target:
                # Emit handoff event
                await self._emitter.emit(HandoffEvent(
                    from_agent=current_agent.name,
                    to_agent=handoff_target.name,
                ))
                await self._emitter.emit(AgentEnd(agent_name=current_agent.name, output="[handoff]"))

                # Switch agent
                current_agent = handoff_target
                await self._emitter.emit(AgentStart(agent_name=current_agent.name))

                # Rebuild messages with new agent's instructions
                system_prompt = current_agent.resolve_instructions(ctx)
                msgs = ctx.build_messages(system_prompt)
                continue

            # Execute tool calls concurrently
            tool_results = await self._execute_tools(current_agent, tool_calls)
            msgs.extend(tool_results)

        # Fallback: max rounds exceeded
        logger.warning("[Runner] hit max rounds (%d), requesting summary", self._max_rounds)
        msgs.append({
            "role": "user",
            "content": tr("runner.max_rounds_fallback"),
        })
        response = await self._llm.generate_with_tools(msgs, [])
        reply = (response.get("content") or tr("runner.max_rounds_default_reply")).strip()
        await self._emitter.emit(AgentEnd(agent_name=current_agent.name, output=reply))
        return RunResult(output=reply, agent_name=current_agent.name, context=ctx)

    # ── Tool execution ────────────────────────────────────────────────────

    async def _execute_tools(
        self,
        agent: Agent,
        tool_calls: list[dict],
    ) -> list[dict]:
        """Run all tool calls concurrently, emitting events for each."""
        # Emit status messages (deduplicated by tool name)
        seen: set[str] = set()
        for tc in tool_calls:
            name = tc["function"]["name"]
            if name not in seen:
                seen.add(name)
                tool = agent.get_tool(name)
                if tool and tool.status_message:
                    status_text = tool.get_status_message()
                    await self._emitter.emit(StatusMessage(text=status_text))

        async def _run_one(tc: dict) -> dict:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            await self._emitter.emit(ToolCallStart(tool_name=name, arguments=args))
            t0 = time.time()

            tool = agent.get_tool(name)
            if tool is None:
                result_str = json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
            else:
                try:
                    result = await tool(**args)
                    result_str = json.dumps(result, ensure_ascii=False)
                except Exception as exc:
                    logger.exception("Tool %s raised an exception", name)
                    result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)

            duration = (time.time() - t0) * 1000
            await self._emitter.emit(ToolCallEnd(
                tool_name=name,
                result=result_str[:500],
                duration_ms=duration,
            ))

            return {
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": result_str,
            }

        return list(await asyncio.gather(*[_run_one(tc) for tc in tool_calls]))

    # ── Handoff detection ─────────────────────────────────────────────────

    def _find_handoff(self, agent: Agent, tool_calls: list[dict]) -> Agent | None:
        """If any tool call is a handoff, return the target agent."""
        for tc in tool_calls:
            name = tc["function"]["name"]
            handoff = agent.get_handoff(name)
            if handoff:
                return handoff.target_agent
        return None

    # ── Guardrails ────────────────────────────────────────────────────────

    async def _run_input_guardrails(
        self,
        agent: Agent,
        ctx: RunContext,
        user_input: str,
    ) -> str | None:
        """Run all input guardrails in parallel. Return rejection message or None."""
        if not agent.input_guardrails:
            return None

        results: list[GuardrailResult] = await asyncio.gather(
            *[g.check(ctx, user_input) for g in agent.input_guardrails]
        )
        for g, result in zip(agent.input_guardrails, results):
            if not result.passed:
                await self._emitter.emit(GuardrailTriggered(
                    guardrail_name=g.name,
                    message=result.reject_message or "输入被拒绝",
                ))
                return result.reject_message or "请求无法处理。"
        return None

    async def _run_output_guardrails(
        self,
        agent: Agent,
        ctx: RunContext,
        output: str,
    ) -> str | None:
        """Run all output guardrails. Return replacement message or None."""
        if not agent.output_guardrails:
            return None

        results: list[GuardrailResult] = await asyncio.gather(
            *[g.check(ctx, output) for g in agent.output_guardrails]
        )
        for g, result in zip(agent.output_guardrails, results):
            if not result.passed:
                await self._emitter.emit(GuardrailTriggered(
                    guardrail_name=g.name,
                    message=result.reject_message or "输出被过滤",
                ))
                return result.reject_message or "抱歉，无法回答这个问题。"
        return None

    # ── LLM call (streaming or non-streaming) ───────────────────────────

    async def _call_llm(self, msgs: list[dict], tool_defs: list[dict]) -> dict:
        """Call the LLM, optionally streaming tokens.

        When streaming is enabled, each text token is emitted as an
        ``LLMTokenDelta`` event so that downstream consumers (e.g. sentence
        splitter → TTS) can start processing before the full reply arrives.

        Returns the same ``{"content": ..., "tool_calls": ...}`` dict
        regardless of whether streaming was used.
        """
        if not self._streaming:
            return await self._llm.generate_with_tools(msgs, tool_defs)

        content_parts: list[str] = []
        tool_calls: list[dict] | None = None

        async for delta in self._llm.generate_with_tools_stream(msgs, tool_defs):
            if delta.token:
                content_parts.append(delta.token)
                await self._emitter.emit(LLMTokenDelta(token=delta.token))
            if delta.tool_calls_delta:
                tool_calls = delta.tool_calls_delta

        return {
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _last_user_message(ctx: RunContext) -> str:
        for msg in reversed(ctx.history):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""
