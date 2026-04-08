"""Smart home agent — controls IoT devices."""

from ..agent_framework import Agent
from ..tools import control_smart_home


smart_home_agent = Agent(
    name="smart_home",
    instructions=(
        "你是智能家居控制助手，专门处理设备开关请求。"
        "使用 control_smart_home 工具执行操作后，简要确认结果。"
        "回答适合语音播报，控制在 1 句。"
    ),
    tools=[control_smart_home],
)
