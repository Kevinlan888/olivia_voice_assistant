"""
get_weather tool implementation using 高德地图 (Amap) Weather API.

Requires AMAP_KEY to be set in .env (高德地图 Web 服务 API Key).
  base  → 返回实况天气 (lives)
  all   → 返回预报天气 (forecast, 当天 + 未来3天)
"""

import logging
from typing import Annotated

import httpx
from pydantic import Field

from ..agent_framework import function_tool
from ..config import settings

logger = logging.getLogger(__name__)

_HTTP = httpx.AsyncClient(timeout=10.0)
_AMAP_BASE = "https://restapi.amap.com/v3"


async def _get_adcode(city: str) -> str | None:
    """Resolve a city name to its Amap adcode via the geocoding API."""
    try:
        resp = await _HTTP.get(
            f"{_AMAP_BASE}/geocode/geo",
            params={"address": city, "key": settings.AMAP_KEY},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            return data["geocodes"][0].get("adcode")
    except Exception as exc:
        logger.warning("[tool:get_weather] geocode failed for %r: %s", city, exc)
    return None


@function_tool(
    description=(
        "获取指定城市的天气信息，包括实况天气（当前气温、天气状况、风向、风力、湿度）"
        "以及未来三天的天气预报（白天/夜晚天气、最高/最低温度）。"
        "当用户询问天气、是否需要带伞、今天热不热、本周天气等问题时调用此工具。"
    ),
    status_message="tool.weather.status",
)
async def get_weather(
    city: Annotated[str, Field(description="城市名称，例如 '北京'、'上海'、'深圳'")],
    forecast: Annotated[bool, Field(description="是否同时返回未来三天预报，默认 False 只返回实况")] = False,
) -> dict:
    """
    Fetch weather for *city* from the Amap Weather API.

    Steps:
      1. Geocode city name → adcode.
      2. Fetch live weather (extensions=base).
      3. Optionally fetch 3-day forecast (extensions=all).
    """
    if not settings.AMAP_KEY:
        return {
            "city": city,
            "error": "AMAP_KEY 未配置",
            "description": f"天气服务未配置，无法查询{city}的天气。",
        }

    adcode = await _get_adcode(city)
    if not adcode:
        return {
            "city": city,
            "error": "无法解析城市编码",
            "description": f'无法识别城市"{city}"，请确认城市名称是否正确。',
        }

    try:
        # ── 实况天气 ──────────────────────────────────────────────────────────
        resp = await _HTTP.get(
            f"{_AMAP_BASE}/weather/weatherInfo",
            params={"key": settings.AMAP_KEY, "city": adcode, "extensions": "base"},
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1" or not data.get("lives"):
            return {
                "city": city,
                "error": data.get("info", "接口返回异常"),
                "description": f"无法获取{city}的天气信息，请稍后重试。",
            }

        live = data["lives"][0]
        result: dict = {
            "city": live.get("city", city),
            "province": live.get("province", ""),
            "condition": live.get("weather", "未知"),
            "temperature_c": int(live.get("temperature", 0)),
            "humidity_pct": int(live.get("humidity", 0)),
            "wind_direction": live.get("winddirection", ""),
            "wind_power": live.get("windpower", ""),
            "report_time": live.get("reporttime", ""),
        }

        result["description"] = (
            f"{result['city']}当前{result['condition']}，"
            f"气温{result['temperature_c']}°C，"
            f"湿度{result['humidity_pct']}%，"
            f"{result['wind_direction']}风{result['wind_power']}级。"
        )

        # ── 预报天气（可选）──────────────────────────────────────────────────
        if forecast:
            f_resp = await _HTTP.get(
                f"{_AMAP_BASE}/weather/weatherInfo",
                params={"key": settings.AMAP_KEY, "city": adcode, "extensions": "all"},
            )
            f_resp.raise_for_status()
            f_data = f_resp.json()

            if f_data.get("status") == "1" and f_data.get("forecasts"):
                casts = f_data["forecasts"][0].get("casts", [])
                result["forecast"] = [
                    {
                        "date": c.get("date"),
                        "week": c.get("week"),
                        "day_weather": c.get("dayweather"),
                        "night_weather": c.get("nightweather"),
                        "day_temp_c": int(c.get("daytemp", 0)),
                        "night_temp_c": int(c.get("nighttemp", 0)),
                        "day_wind": c.get("daywind"),
                        "day_wind_power": c.get("daypower"),
                    }
                    for c in casts
                ]
                if result["forecast"]:
                    today = result["forecast"][0]
                    result["description"] += (
                        f" 今日白天{today['day_weather']}，"
                        f"最高{today['day_temp_c']}°C；"
                        f"夜间{today['night_weather']}，"
                        f"最低{today['night_temp_c']}°C。"
                    )

        logger.info("[tool:get_weather] %s", result)
        return result

    except Exception as exc:
        logger.warning("[tool:get_weather] failed: %s", exc)
        return {
            "city": city,
            "error": str(exc),
            "description": f"无法获取{city}的天气信息，请稍后重试。",
        }
