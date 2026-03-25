import json
import logging
import httpx
from .base import BaseLLM
from ..config import settings

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    """Async LLM client for a local Ollama instance.

    Uses Ollama's /api/chat endpoint (OpenAI-compatible).
    Tool calling is supported natively by models such as
    qwen2.5, llama3.1, mistral-nemo — pass OLLAMA_MODEL accordingly.
    """

    def __init__(self):
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._model = settings.OLLAMA_MODEL
        self._http = httpx.AsyncClient(timeout=120.0)
        logger.info("Ollama LLM ready: model=%s url=%s", self._model, self._base_url)

    async def generate(self, messages: list[dict]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 512},
        }
        response = await self._http.post(f"{self._base_url}/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()

    async def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call Ollama /api/chat with optional tool definitions.

        Ollama mirrors the OpenAI tool-call response shape when the loaded
        model supports it.  Falls back gracefully for models that do not.
        """
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1024},
        }
        if tools:
            payload["tools"] = tools

        response = await self._http.post(f"{self._base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        msg = data.get("message", {})

        # Ollama wraps tool calls under message.tool_calls
        raw_calls = msg.get("tool_calls") or []
        tool_calls = None
        if raw_calls:
            tool_calls = []
            for i, tc in enumerate(raw_calls):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                tool_calls.append({
                    "id": tc.get("id", f"call_{i}"),
                    "function": {
                        "name": fn.get("name", ""),
                        # Ollama may return a dict; serialise for uniform handling
                        "arguments": json.dumps(args, ensure_ascii=False)
                                     if isinstance(args, dict) else str(args),
                    },
                })

        return {"content": msg.get("content") or "", "tool_calls": tool_calls}
