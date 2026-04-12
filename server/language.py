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
