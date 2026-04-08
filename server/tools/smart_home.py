"""
control_smart_home tool implementation.

MVP maintains an in-memory device state store.
For production, replace _execute_command() with your MQTT / Home Assistant /
Zigbee2MQTT / Tuya SDK calls.
"""

import asyncio
import logging
from typing import Annotated, Literal

from pydantic import Field

from ..agent_framework import function_tool

logger = logging.getLogger(__name__)

# Simulated device registry  {device_name → current_status}
_DEVICE_STATE: dict[str, str] = {
    "客厅灯": "off",
    "卧室灯": "off",
    "空调": "off",
    "电视": "off",
    "窗帘": "off",
    "风扇": "off",
}


@function_tool(
    description=(
        "控制智能家居设备的开关或状态。"
        "当用户说'帮我开灯'、'关空调'、'把电视关掉'等时调用此工具。"
    ),
    status_message="正在控制设备...",
)
async def control_smart_home(
    device: Annotated[str, Field(description="设备名称，例如 '客厅灯'、'空调'、'电视'、'窗帘'")],
    status: Annotated[Literal["on", "off", "toggle"], Field(description="目标状态：on=打开, off=关闭, toggle=切换")],
) -> dict:
    """
    Control a smart home device.

    Args:
        device: Device name (e.g. '客厅灯')
        status: 'on', 'off', or 'toggle'

    Returns:
        dict with keys: device, requested_status, actual_status,
                        success, description
    """
    # Simulate a short I/O delay (replace with real SDK awaitable)
    await asyncio.sleep(0.3)

    # Resolve toggle
    if status == "toggle":
        current = _DEVICE_STATE.get(device, "off")
        status = "off" if current == "on" else "on"

    # Register new state (auto-add unknown devices)
    _DEVICE_STATE[device] = status

    action_word = "打开" if status == "on" else "关闭"
    result = {
        "device": device,
        "requested_status": status,
        "actual_status": _DEVICE_STATE[device],
        "success": True,
        "description": f"好的，已经{action_word}{device}。",
    }
    logger.info("[tool:smart_home] %s → %s", device, status)
    return result
