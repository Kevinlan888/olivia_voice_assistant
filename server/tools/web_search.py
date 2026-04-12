"""web_search tool implementation powered by SerpAPI."""

import logging
from typing import Annotated

import httpx
from pydantic import Field

from ..agent_framework import function_tool
from ..config import settings

logger = logging.getLogger(__name__)

_HTTP = httpx.AsyncClient(
    timeout=15.0,
    headers={"User-Agent": "Olivia-VoiceAssistant/1.0 (web_search tool)"},
)
_SERPAPI_URL = "https://serpapi.com/search.json"


@function_tool(
    description=(
        "在互联网上搜索最新信息。当问题需要实时数据、新闻、"
        "价格、赛事结果等训练数据截止日期之后的内容时调用此工具。"
    ),
    status_message="正在联网搜索...",
)
async def web_search(
    query: Annotated[str, Field(description="搜索关键词或自然语言查询")],
) -> dict:
    """
    Search the web for *query* and return a brief summary.

    Returns a dict with keys:
        query, results (list of {title, snippet, url}), description
    """
    api_key = settings.SERPAPI_KEY.strip()
    if not api_key:
        return {
            "query": query,
            "results": [],
            "error": "SERPAPI_KEY is missing",
            "description": "未配置 SERPAPI_KEY，无法进行联网搜索。",
        }

    is_english = settings.WHISPER_LANGUAGE.lower() in ("en", "english")
    params = {
        "q": query,
        "api_key": api_key,
        "engine": settings.SERPAPI_ENGINE,
        "hl": "en" if is_english else "zh-cn",
        "gl": "us" if is_english else "cn",
    }

    try:
        resp = await _HTTP.get(_SERPAPI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []

        # Prefer answer_box when SerpAPI extracts a direct answer.
        answer_box = data.get("answer_box") or {}
        answer = (
            answer_box.get("answer")
            or answer_box.get("snippet")
            or answer_box.get("result")
            or ""
        )
        if answer:
            results.append({
                "title": answer_box.get("title") or query,
                "snippet": str(answer),
                "url": answer_box.get("link") or "",
            })

        for item in (data.get("organic_results") or [])[:5]:
            title = item.get("title")
            if title:
                results.append({
                    "title": title,
                    "snippet": item.get("snippet") or "",
                    "url": item.get("link") or "",
                })

        if results:
            top = results[0]["snippet"][:200]
            description = f'搜索"{query}"的结果：{top}'
        else:
            description = f'未找到关于"{query}"的相关信息，建议直接访问搜索引擎查询。'

        result = {"query": query, "results": results[:4], "description": description}
        logger.info("[tool:web_search] query=%r found=%d", query, len(results))
        return result

    except Exception as exc:
        logger.warning("[tool:web_search] failed: %s", exc)
        return {
            "query": query,
            "results": [],
            "error": str(exc),
            "description": f'搜索"{query}"时出现错误，请稍后重试。',
        }
