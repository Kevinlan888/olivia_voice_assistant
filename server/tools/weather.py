"""
get_weather tool implementation.

MVP uses wttr.in (free, no API key) with a JSON API.
For production, swap in OpenWeatherMap or any paid provider.
"""

import logging
from typing import Annotated

import httpx
from pydantic import Field

from ..agent_framework import function_tool

logger = logging.getLogger(__name__)

_HTTP = httpx.AsyncClient(timeout=10.0)


@function_tool(
    description=(
        "获取指定城市当前或未来24小时的天气信息，包括温度、天气状况和降雨概率。"
        "当用户询问天气、是否需要带伞、今天热不热等问题时调用此工具。"
    ),
    status_message="正在查询天气...",
)
async def get_weather(
    city: Annotated[str, Field(description="城市名称，例如 '北京'、'上海'、'深圳'")],
) -> dict:
    """
    Fetch current weather for *city* from wttr.in.

    Returns a dict with keys:
        city, condition, temp_c, feels_like_c, humidity_pct,
        rain_chance_pct, wind_kph, description
    """
    url = f"https://wttr.in/{city}?format=j1&lang=zh"
    try:
        resp = await _HTTP.get(url)
        resp.raise_for_status()
        data = resp.json()

        current = data["current_condition"][0]
        weather_desc = current.get("lang_zh", [{}])[0].get("value", current.get("weatherDesc", [{}])[0].get("value", "未知"))
        
        # Tomorrow's hourly rain chance (first entry of day index 1)
        tomorrow = data.get("weather", [None, None])[1]
        rain_chance = 0
        if tomorrow:
            rain_hour = tomorrow.get("hourly", [{}])[0]
            rain_chance = int(rain_hour.get("chanceofrain", 0))

        result = {
            "city": city,
            "condition": weather_desc,
            "temp_c": int(current["temp_C"]),
            "feels_like_c": int(current["FeelsLikeC"]),
            "humidity_pct": int(current["humidity"]),
            "rain_chance_pct": rain_chance,
            "wind_kph": int(current["windspeedKmph"]),
        }
        result["description"] = (
            f"{city}当前{result['condition']}，气温{result['temp_c']}°C，"
            f"体感{result['feels_like_c']}°C，湿度{result['humidity_pct']}%，"
            f"明天降雨概率{result['rain_chance_pct']}%。"
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
