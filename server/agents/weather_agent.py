"""Weather agent — handles weather queries."""

from ..agent_framework import Agent
from ..tools import get_weather


weather_agent = Agent(
    name="weather",
    instructions=(
        "你是天气查询助手，专门回答天气相关问题。"
        "使用 get_weather 工具获取数据后，用自然口语简要告知用户天气情况。"
        "回答适合语音播报，不使用 Markdown 或特殊格式。"
        "控制在 1 到 3 句。"
    ),
    tools=[get_weather],
)
