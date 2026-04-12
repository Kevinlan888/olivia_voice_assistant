"""Search agent — web search for real-time information."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..config import settings
from ..tools import web_search


def _search_instructions(ctx: RunContext) -> str:
    is_english = settings.WHISPER_LANGUAGE.lower() in ("en", "english")
    if is_english:
        return (
            "You are a web search assistant. Use the web_search tool to find real-time "
            "information. Search using English keywords that best match the user's intent. "
            "After getting results, briefly summarise in 1–3 spoken sentences. "
            "No Markdown, no bullet points, no links."
        )
    return (
        "你是联网搜索助手，负责查找实时信息。"
        "使用 web_search 工具时，用中文关键词搜索。"
        "获取结果后，用口语化的方式简要总结给用户。"
        "回答适合语音播报，不使用 Markdown 或链接。"
        "控制在 1 到 3 句。"
    )


search_agent = Agent(
    name="search",
    instructions=_search_instructions,
    tools=[web_search],
)
