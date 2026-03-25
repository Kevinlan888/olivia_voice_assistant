"""
OpenAI-format tool definitions (JSON Schema).

Each entry in TOOL_DEFINITIONS is passed verbatim to the
`tools` parameter of the chat completions API.
"""

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "获取指定城市当前或未来24小时的天气信息，包括温度、天气状况和降雨概率。"
                "当用户询问天气、是否需要带伞、今天热不热等问题时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如 '北京'、'上海'、'深圳'",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_smart_home",
            "description": (
                "控制智能家居设备的开关或状态。"
                "当用户说'帮我开灯'、'关空调'、'把电视关掉'等时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": "设备名称，例如 '客厅灯'、'空调'、'电视'、'窗帘'",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["on", "off", "toggle"],
                        "description": "目标状态：on=打开, off=关闭, toggle=切换",
                    },
                },
                "required": ["device", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "在互联网上搜索最新信息。当问题需要实时数据、新闻、"
                "价格、赛事结果等训练数据截止日期之后的内容时调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或自然语言查询",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# Human-readable status messages shown to the user while a tool runs
TOOL_STATUS_MESSAGES: dict[str, str] = {
    "get_weather": "正在查询天气...",
    "control_smart_home": "正在控制设备...",
    "web_search": "正在联网搜索...",
}
