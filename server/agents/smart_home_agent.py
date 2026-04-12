"""Smart home agent — controls IoT devices."""

from ..agent_framework import Agent
from ..agent_framework.context import RunContext
from ..language import tr
from ..tools import control_smart_home


smart_home_agent = Agent(
    name="smart_home",
    instructions=lambda ctx: tr("agent.smart_home.instructions"),
    tools=[control_smart_home],
)
