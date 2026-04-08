"""
Olivia multi-agent definitions.

Provides ``create_default_agent()`` which builds the agent graph:
    router → [chat, weather, smart_home, search]
"""

from .router_agent import create_router_agent

__all__ = ["create_router_agent"]
