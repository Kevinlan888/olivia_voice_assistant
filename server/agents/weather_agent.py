"""Weather agent — handles weather queries."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..language import tr
from ..tools import get_weather


weather_agent = Agent(
    name="weather",
    instructions=lambda ctx: tr("agent.weather.instructions"),
    tools=[get_weather],
)
