"""Search agent — web search for real-time information."""

from ..agent_framework import Agent
from ..tools import web_search


search_agent = Agent(
    name="search",
    instructions=(
        "你是联网搜索助手，负责查找实时信息。"
        "使用 web_search 工具获取结果后，用口语化的方式简要总结给用户。"
        "回答适合语音播报，不使用 Markdown 或链接。"
        "控制在 1 到 3 句。"
    ),
    tools=[web_search],
)
