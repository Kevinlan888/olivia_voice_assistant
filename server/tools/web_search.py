"""
web_search tool implementation.

Uses DuckDuckGo Instant Answer API (free, no API key).
For production consider: Brave Search API, Tavily, Serper, or SerpAPI.
"""

import logging
import httpx

logger = logging.getLogger(__name__)

_HTTP = httpx.AsyncClient(
    timeout=15.0,
    headers={"User-Agent": "Olivia-VoiceAssistant/1.0 (web_search tool)"},
)
_DDG_URL = "https://api.duckduckgo.com/"


async def web_search(query: str) -> dict:
    """
    Search the web for *query* and return a brief summary.

    Returns a dict with keys:
        query, results (list of {title, snippet, url}), description
    """
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    try:
        resp = await _HTTP.get(_DDG_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []

        # Instant Answer (best result)
        abstract = data.get("AbstractText", "").strip()
        abstract_url = data.get("AbstractURL", "")
        if abstract:
            results.append({"title": data.get("Heading", query), "snippet": abstract, "url": abstract_url})

        # Related topics
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:60],
                    "snippet": topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                })

        if results:
            top = results[0]["snippet"][:200]
            description = f"搜索"{query}"的结果：{top}"
        else:
            description = f"未找到关于"{query}"的相关信息，建议直接访问搜索引擎查询。"

        result = {"query": query, "results": results[:4], "description": description}
        logger.info("[tool:web_search] query=%r found=%d", query, len(results))
        return result

    except Exception as exc:
        logger.warning("[tool:web_search] failed: %s", exc)
        return {
            "query": query,
            "results": [],
            "error": str(exc),
            "description": f"搜索"{query}"时出现错误，请稍后重试。",
        }
