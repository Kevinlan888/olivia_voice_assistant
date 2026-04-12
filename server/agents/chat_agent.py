"""Chat agent — general conversation, no tools."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..language import tr


chat_agent = Agent(
    name="chat",
    instructions=lambda ctx: tr("agent.chat.instructions"),
    tools=[],
)
