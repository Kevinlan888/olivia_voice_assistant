"""Search agent — web search for real-time information."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..language import lang
from ..tools import web_search


def _search_instructions(ctx: RunContext) -> str:
    return lang.agent_instructions("agent.search.instructions")


search_agent = Agent(
    name="search",
    instructions=_search_instructions,
    tools=[web_search],
)
