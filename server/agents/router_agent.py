"""Router agent — dispatches to specialized sub-agents via handoffs."""

from __future__ import annotations

from datetime import datetime

from ..agent_framework import Agent, Handoff, RunContext
from ..config import settings
from .chat_agent import chat_agent
from .weather_agent import weather_agent
from .smart_home_agent import smart_home_agent
from .search_agent import search_agent
from ..language import lang, tr


def _build_router_instructions(ctx: RunContext) -> str:
    """Dynamic system prompt with real-time context."""
    now = ctx.now
    timezone_name = now.tzname() or "local"
    current_time_text = now.strftime("%Y-%m-%d %H:%M:%S")

    if lang.is_english:
        weekday_text = now.strftime("%A")
        base_prompt = settings.SYSTEM_PROMPT_EN
    else:
        weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_text = weekday_map[now.weekday()]
        base_prompt = settings.SYSTEM_PROMPT

    time_context = tr(
        "router.time_context",
        time=current_time_text,
        weekday=weekday_text,
        timezone=timezone_name,
    )
    routing_instructions = tr("router.routing_instructions")

    return f"{base_prompt}\n\n{time_context}{routing_instructions}\n\n{tr('agent.language_enforcement')}"


def create_router_agent() -> Agent:
    """Build the top-level router agent with handoffs to sub-agents."""
    return Agent(
        name="olivia",
        instructions=_build_router_instructions,
        handoffs=[
            Handoff(
                target_agent=weather_agent,
                description=tr("handoff.weather.description"),
            ),
            Handoff(
                target_agent=smart_home_agent,
                description=tr("handoff.smart_home.description"),
            ),
            Handoff(
                target_agent=search_agent,
                description=tr("handoff.search.description"),
            ),
        ],
    )
