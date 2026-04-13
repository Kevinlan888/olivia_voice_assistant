"""Chat agent — general conversation, no tools."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..language import lang


chat_agent = Agent(
    name="chat",
    instructions=lambda ctx: lang.agent_instructions("agent.chat.instructions"),
    tools=[],
)
