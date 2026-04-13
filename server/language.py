"""Global language manager and translation (tr) system.

Inspired by Qt's ``tr()`` — pass a dot-separated key, get back the string
for the current language.  Adding a new language is a single dict entry.

Usage::

    from .language import tr, lang

    # Key-based lookup (preferred)
    msg = tr("tool.web_search.status")   # → "Searching the web..." or "正在联网搜索..."

    # Language helpers
    if lang.is_english: ...
    params["hl"] = lang.serpapi_hl
    model.transcribe(audio, language=lang.whisper_lang)
"""

from .config import settings

# ── Translation table ─────────────────────────────────────────────────────────
# Format: { key: { lang_code: translated_string } }
# lang_codes match the normalised first segment of WHISPER_LANGUAGE ("zh", "en", …)

_TRANSLATIONS: dict[str, dict[str, str]] = {

    # ── Tool status messages ──────────────────────────────────────────────────
    "tool.web_search.status": {
        "zh": "正在联网搜索...",
        "en": "Searching the web...",
    },
    "tool.weather.status": {
        "zh": "正在查询天气...",
        "en": "Checking the weather...",
    },
    "tool.smart_home.status": {
        "zh": "正在控制设备...",
        "en": "Controlling the device...",
    },

    # ── Agent instructions ────────────────────────────────────────────────────
    "agent.search.instructions": {
        "zh": (
            "你是联网搜索助手，负责查找实时信息。"
            "使用 web_search 工具时，用中文关键词搜索。"
            "获取结果后，用口语化的方式简要总结给用户。"
            "回答适合语音播报，不使用 Markdown 或链接。"
            "控制在 1 到 3 句。"
        ),
        "en": (
            "You are a web search assistant. Use the web_search tool to find real-time "
            "information. Search using English keywords that best match the user's intent. "
            "After getting results, briefly summarise in 1–3 spoken sentences. "
            "No Markdown, no bullet points, no links."
        ),
    },

    # ── Router: routing rule block appended to the system prompt ─────────────
    "router.routing_instructions": {
        "zh": (
            "\n\n你可以将请求转交给专项助手处理。规则如下：\n"
            "- 天气相关问题 → 转交 weather 助手\n"
            "- 智能家居控制（开灯、关空调等）→ 转交 smart_home 助手\n"
            "- 需要联网搜索的实时信息 → 转交 search 助手\n"
            "- 闲聊、常识问答等 → 自己直接回答，不需要转交\n"
            "如果不确定是否需要转交，先尝试自己回答。"
        ),
        "en": (
            "\n\nYou can hand off requests to specialised sub-agents. Rules:\n"
            "- Weather questions → hand off to the weather agent\n"
            "- Smart-home control (lights, AC, TV, etc.) → hand off to the smart_home agent\n"
            "- Real-time information requiring a web search → hand off to the search agent\n"
            "- Casual conversation and general knowledge → answer directly, no handoff needed\n"
            "When in doubt, try answering yourself first."
        ),
    },

    # ── Router: time context block ────────────────────────────────────────────
    "router.time_context": {
        "zh": (
            "以下是系统提供的实时上下文，请当作事实使用：\n"
            "- 当前本地时间：{time}\n"
            "- 星期：{weekday}\n"
            "- 时区：{timezone}\n"
            "当用户提到今天、明天、后天、现在、今晚、本周等相对时间时，"
            "请以上述当前时间为准进行理解和回答。"
        ),
        "en": (
            "The following real-time context is provided by the system — treat it as fact:\n"
            "- Current local time: {time}\n"
            "- Day of week: {weekday}\n"
            "- Timezone: {timezone}\n"
            "When the user mentions relative time expressions such as today, tomorrow, "
            "the day after tomorrow, now, tonight, or this week, interpret and answer "
            "based on the current time above."
        ),
    },

    # ── Sub-agent instructions ────────────────────────────────────────────────
    "agent.weather.instructions": {
        "zh": (
            "你是天气查询助手，专门回答天气相关问题。"
            "使用 get_weather 工具获取数据后，用自然口语简要告知用户天气情况。"
            "回答适合语音播报，不使用 Markdown 或特殊格式。"
            "控制在 1 到 3 句。"
        ),
        "en": (
            "You are a weather assistant. Use the get_weather tool to fetch data, "
            "then give a brief spoken summary of the weather conditions. "
            "No Markdown or special formatting. Keep it to 1–3 sentences."
        ),
    },
    "agent.smart_home.instructions": {
        "zh": (
            "你是智能家居控制助手，专门处理设备开关请求。"
            "使用 control_smart_home 工具执行操作后，简要确认结果。"
            "回答适合语音播报，控制在 1 句。"
        ),
        "en": (
            "You are a smart home assistant. Use the control_smart_home tool to execute "
            "device commands, then briefly confirm the result in one spoken sentence."
        ),
    },
    "agent.chat.instructions": {
        "zh": (
            "你是 Olivia，一个友好、简洁、自然的中文语音助手。"
            "你的回答会被直接用于语音播报。"
            "请只输出适合朗读的纯文本口语句子，不使用 Markdown、标题、列表、编号、表情或特殊符号。"
            "优先直接回答用户问题，通常控制在 1 到 3 句。"
        ),
        "en": (
            "You are Olivia, a friendly and concise voice assistant. "
            "Your responses will be read aloud directly by a TTS engine. "
            "Reply with plain spoken English only — no Markdown, bullet points, headers, "
            "numbered lists, emojis, or special symbols. Keep replies to 1–3 sentences."
        ),
    },

    # ── Handoff ───────────────────────────────────────────────────────────────
    "handoff.default_description": {
        "zh": "将对话转交给 {agent} 处理。当你认为 {agent} 更适合回答当前问题时调用此工具。",
        "en": "Hand off the conversation to the {agent} agent when it is better suited to answer.",
    },
    "handoff.weather.description": {
        "zh": "转交给天气查询助手，处理天气、温度、降水等问题。",
        "en": "Hand off to the weather agent for weather, temperature, and forecast questions.",
    },
    "handoff.smart_home.description": {
        "zh": "转交给智能家居助手，控制灯、空调、电视等设备。",
        "en": "Hand off to the smart home agent to control lights, AC, TV, and other devices.",
    },
    "handoff.search.description": {
        "zh": "转交给联网搜索助手，搜索实时新闻、价格、赛事等信息。",
        "en": "Hand off to the search agent for real-time information like news, prices, or events.",
    },

    # ── Runner internals ──────────────────────────────────────────────────────
    "runner.max_rounds_fallback": {
        "zh": "请根据以上工具调用结果，给我一个简洁的语音回复。",
        "en": "Based on the tool results above, give a brief spoken reply.",
    },
    "runner.max_rounds_default_reply": {
        "zh": "处理完成。",
        "en": "Done.",
    },

    # ── Language enforcement suffix ──────────────────────────────────────────
    "agent.language_enforcement": {
        "zh": "无论工具返回的数据是什么语言，你的回复必须用中文。",
        "en": (
            "IMPORTANT: Always reply in English, regardless of the language returned "
            "by any tool. Translate tool results into English before responding."
        ),
    },

    # ── Context summary ───────────────────────────────────────────────────────
    "context.summary_prompt": {
        "zh": (
            "请将以下对话历史浓缩为简短的中文摘要（不超过 200 字）。"
            "保留关键信息、用户偏好和未完成的任务，省略寒暄和重复内容。\n\n"
        ),
        "en": (
            "Summarise the following conversation history in a concise English paragraph "
            "(under 150 words). Preserve key facts, user preferences, and unfinished tasks. "
            "Omit small talk and repetition.\n\n"
        ),
    },
}

# Fallback order when the exact language code is not found in an entry
_FALLBACK_ORDER = ("en", "zh")


# ── LanguageManager ───────────────────────────────────────────────────────────

class LanguageManager:
    """Centralises all language/locale decisions for the server.

    All properties read ``settings.WHISPER_LANGUAGE`` at call time, so
    changing the setting at runtime is reflected immediately.
    """

    @property
    def code(self) -> str:
        """Normalised language code — first segment, lower-cased.

        ``"zh-CN"`` → ``"zh"``,  ``"en-US"`` → ``"en"``,  ``"auto"`` → ``"auto"``
        """
        return settings.WHISPER_LANGUAGE.lower().split("-")[0]

    @property
    def is_english(self) -> bool:
        return self.code in ("en", "english")

    def tr(self, key: str, **fmt: str) -> str:
        """Return the translation for *key* in the current language.

        Unknown keys are returned unchanged (safe fallback).
        Optional keyword arguments are interpolated via ``str.format_map``.

        Example::

            tr("router.time_context", time="12:00", weekday="Monday", timezone="UTC")
        """
        entry = _TRANSLATIONS.get(key)
        if entry is None:
            return key  # unknown key — return as-is

        code = self.code
        text = entry.get(code)
        if text is None:
            for fb in _FALLBACK_ORDER:
                text = entry.get(fb)
                if text is not None:
                    break
        if text is None:
            text = next(iter(entry.values()), key)

        return text.format_map(fmt) if fmt else text

    # ── SerpAPI locale ────────────────────────────────────────────────────────

    def agent_instructions(self, base_key: str) -> str:
        """Return agent instructions with the language-enforcement suffix appended."""
        return self.tr(base_key) + " " + self.tr("agent.language_enforcement")

    @property
    def serpapi_hl(self) -> str:
        return "en" if self.is_english else "zh-cn"

    @property
    def serpapi_gl(self) -> str:
        return "us" if self.is_english else "cn"

    # ── ASR ───────────────────────────────────────────────────────────────────

    @property
    def whisper_lang(self) -> str | None:
        """Language string for Whisper, or ``None`` for auto-detect."""
        raw = settings.WHISPER_LANGUAGE
        return None if raw == "auto" else raw


#: Process-wide singleton.
lang = LanguageManager()


def tr(key: str, **fmt: str) -> str:
    """Module-level shorthand for ``lang.tr(key, **fmt)``."""
    return lang.tr(key, **fmt)
