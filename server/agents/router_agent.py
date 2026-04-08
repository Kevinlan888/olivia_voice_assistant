"""Router agent — dispatches to specialized sub-agents via handoffs."""

from __future__ import annotations

from datetime import datetime

from ..agent_framework import Agent, Handoff, RunContext
from ..config import settings
from .chat_agent import chat_agent
from .weather_agent import weather_agent
from .smart_home_agent import smart_home_agent
from .search_agent import search_agent


def _build_router_instructions(ctx: RunContext) -> str:
    """Dynamic system prompt with real-time context."""
    now = ctx.now
    timezone_name = now.tzname() or "local"
    current_time_text = now.strftime("%Y-%m-%d %H:%M:%S")

    is_english = settings.WHISPER_LANGUAGE.lower() in ("en", "english")

    if is_english:
        weekday_text = now.strftime("%A")
        base_prompt = settings.SYSTEM_PROMPT_EN
        time_context = (
            f"The following real-time context is provided by the system — treat it as fact:\n"
            f"- Current local time: {current_time_text}\n"
            f"- Day of week: {weekday_text}\n"
            f"- Timezone: {timezone_name}"
        )
    else:
        weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_text = weekday_map[now.weekday()]
        base_prompt = settings.SYSTEM_PROMPT
        time_context = (
            "以下是系统提供的实时上下文，请当作事实使用：\n"
            f"- 当前本地时间：{current_time_text}\n"
            f"- 星期：{weekday_text}\n"
            f"- 时区：{timezone_name}\n"
            "当用户提到今天、明天、后天、现在、今晚、本周等相对时间时，"
            "请以上述当前时间为准进行理解和回答。"
        )

    routing_instructions = (
        "\n\n你可以将请求转交给专项助手处理。规则如下：\n"
        "- 天气相关问题 → 转交 weather 助手\n"
        "- 智能家居控制（开灯、关空调等）→ 转交 smart_home 助手\n"
        "- 需要联网搜索的实时信息 → 转交 search 助手\n"
        "- 闲聊、常识问答等 → 自己直接回答，不需要转交\n"
        "如果不确定是否需要转交，先尝试自己回答。"
    )

    return f"{base_prompt}\n\n{time_context}{routing_instructions}"


def create_router_agent() -> Agent:
    """Build the top-level router agent with handoffs to sub-agents."""
    return Agent(
        name="olivia",
        instructions=_build_router_instructions,
        handoffs=[
            Handoff(
                target_agent=weather_agent,
                description="转交给天气查询助手，处理天气、温度、降水等问题。",
            ),
            Handoff(
                target_agent=smart_home_agent,
                description="转交给智能家居助手，控制灯、空调、电视等设备。",
            ),
            Handoff(
                target_agent=search_agent,
                description="转交给联网搜索助手，搜索实时新闻、价格、赛事等信息。",
            ),
        ],
    )
