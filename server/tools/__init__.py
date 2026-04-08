from .weather import get_weather
from .smart_home import control_smart_home
from .web_search import web_search

# For backward compat, expose the legacy constants derived from FunctionTool objects.
# New code should use the FunctionTool instances directly.
ALL_TOOLS = [get_weather, control_smart_home, web_search]

TOOL_DEFINITIONS = [t.definition for t in ALL_TOOLS]
TOOL_STATUS_MESSAGES = {t.name: t.status_message for t in ALL_TOOLS if t.status_message}

__all__ = [
    "get_weather",
    "control_smart_home",
    "web_search",
    "ALL_TOOLS",
    "TOOL_DEFINITIONS",
    "TOOL_STATUS_MESSAGES",
]
