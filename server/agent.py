"""
ToolAgent — Agentic loop with OpenAI-style Function Calling.

Protocol
--------
The agent drives the following loop:

  1. Send messages (+ tool definitions) to the LLM.
  2. If LLM response contains tool_calls:
       a. Emit a STATUS:<message> signal via the `status_cb` hook so the
          client can play a "hold on" prompt immediately.
       b. Execute all requested tools concurrently (asyncio.gather).
       c. Append tool results to the message list.
       d. Go back to step 1.
  3. When LLM returns a plain text reply (no tool_calls), return it.

The loop is capped at MAX_TOOL_ROUNDS to prevent infinite cycles.

Compatibility
-------------
* OpenAI API / any OpenAI-compatible endpoint  → uses native tool-calling.
* Ollama                                        → uses a prompt-based fallback
  (Ollama's function-calling support is model-dependent; models like
   qwen2.5, llama3.1, and mistral-nemo support it natively via the
   /api/chat?tools= parameter).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .tools import (
    TOOL_DEFINITIONS,
    TOOL_STATUS_MESSAGES,
    get_weather,
    control_smart_home,
    web_search,
)

logger = logging.getLogger(__name__)

# Maximum function-call rounds before giving up
MAX_TOOL_ROUNDS = 5

# Dispatch table  {function_name → async callable}
_TOOL_REGISTRY: dict[str, Callable[..., Awaitable[dict]]] = {
    "get_weather": get_weather,
    "control_smart_home": control_smart_home,
    "web_search": web_search,
}

# Type alias for the status callback
StatusCallback = Callable[[str], Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _call_tool(name: str, arguments: dict) -> str:
    """Execute a single tool and return its result as a JSON string."""
    fn = _TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    try:
        result = await fn(**arguments)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Tool %s raised an exception", name)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def _execute_tool_calls(
    tool_calls: list[dict],
    status_cb: StatusCallback,
) -> list[dict]:
    """
    Run all tool calls concurrently and return a list of
    role='tool' messages ready to be appended to the conversation.

    Fires status_cb ONCE per unique tool name (deduplicated) before execution.
    """
    # Collect unique tool names and send status signals
    seen: set[str] = set()
    for tc in tool_calls:
        name = tc["function"]["name"]
        if name not in seen:
            seen.add(name)
            msg = TOOL_STATUS_MESSAGES.get(name, "正在处理...")
            await status_cb(msg)

    # Execute all tool calls concurrently
    async def _run_one(tc: dict) -> dict:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"].get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        logger.info("[Agent] calling tool %s(%s)", name, args)
        result_json = await _call_tool(name, args)
        logger.info("[Agent] tool %s → %s", name, result_json[:120])
        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": name,
            "content": result_json,
        }

    return list(await asyncio.gather(*[_run_one(tc) for tc in tool_calls]))


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

class ToolAgent:
    """
    Async agentic loop that wraps any LLM client supporting tool-calling.

    Args:
        llm_client: An object exposing `generate_with_tools(messages, tools)`.
                    See OpenAILLM.generate_with_tools() for the contract.
        status_cb:  An async callable(str) that receives human-readable
                    status strings (e.g. "正在查询天气...") during tool execution.
                    Typically sends `STATUS:<msg>` to the WebSocket client.
    """

    def __init__(self, llm_client: Any, status_cb: StatusCallback):
        self._llm = llm_client
        self._status_cb = status_cb

    async def run(self, messages: list[dict]) -> str:
        """
        Drive the tool-calling loop until a final text response is produced.

        Args:
            messages: Full message list including system prompt + history.

        Returns:
            The assistant's final natural-language reply.
        """
        msgs = list(messages)  # shallow copy – we'll append tool results

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            logger.info("[Agent] round %d, %d messages", round_num, len(msgs))

            response = await self._llm.generate_with_tools(msgs, TOOL_DEFINITIONS)

            # ── Plain text reply → done ────────────────────────────────────
            if not response.get("tool_calls"):
                return response.get("content", "").strip()

            # ── Tool call(s) requested ─────────────────────────────────────
            tool_calls = response["tool_calls"]
            logger.info("[Agent] %d tool call(s) requested", len(tool_calls))

            # Append the assistant's "I want to call tool X" turn
            msgs.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            })

            # Execute tools and collect results
            tool_results = await _execute_tool_calls(tool_calls, self._status_cb)
            msgs.extend(tool_results)

        # Fallback: ran out of rounds without a plain reply
        logger.warning("[Agent] hit MAX_TOOL_ROUNDS (%d), asking for summary", MAX_TOOL_ROUNDS)
        msgs.append({
            "role": "user",
            "content": "请根据以上工具调用结果，给我一个简洁的中文语音回复。",
        })
        response = await self._llm.generate_with_tools(msgs, [])
        return response.get("content", "处理完成。").strip()
