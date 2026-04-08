from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # ── ASR ──────────────────────────────────────────────────────────────────
    WHISPER_MODEL: str = "base"          # tiny / base / small / medium / large-v3
    WHISPER_DEVICE: str = "cpu"          # cpu / cuda / mlx
    WHISPER_COMPUTE_TYPE: str = "int8"   # int8 / float16 / float32 (ignored for mlx)

    WHISPER_LANGUAGE: str = "zh"         # zh / en / ja / … or "auto" for auto-detect

    # ── LLM ──────────────────────────────────────────────────────────────────
    LLM_PROVIDER: Literal["openai", "ollama"] = "ollama"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"

    # ── TTS ──────────────────────────────────────────────────────────────────
    TTS_PROVIDER: Literal["edge", "sovits"] = "edge"
    EDGE_TTS_VOICE: str = "zh-CN-XiaoxiaoNeural"

    SOVITS_BASE_URL: str = "http://localhost:9880"

    # When True the server synthesises short status phrases ("正在搜索...")
    # and pushes them as audio to the client before the final reply is ready.
    # Set to False to send STATUS: text frames only (client handles the audio).
    TTS_STATUS_AUDIO: bool = True

    # ── Conversation ─────────────────────────────────────────────────────────
    SYSTEM_PROMPT: str = (
        "你是 Olivia，一个友好、简洁、自然的中文语音助手。"
        "你的回答会被直接用于语音播报。"
        "请只输出适合朗读的纯文本口语句子，不使用 Markdown、标题、列表、编号、表情或特殊符号。"
        "优先直接回答用户问题，通常控制在 1 到 3 句。"
        "如果需要基于日期或时间做判断，请结合系统提供的当前时间信息。"
    )
    SYSTEM_PROMPT_EN: str = (
        "You are Olivia, a friendly and concise voice assistant. "
        "Your responses will be read aloud directly by a TTS engine. "
        "Reply with plain spoken English only — no Markdown, bullet points, headers, "
        "numbered lists, emojis, or special symbols. "
        "Be direct: give the answer first, then a brief clarification if needed. "
        "Keep replies to 1–3 sentences. "
        "If the user's question involves relative time expressions (today, tomorrow, now, etc.), "
        "use the current time provided by the system context."
    )
    MAX_CONTEXT_TOKENS: int = 8192
    ENABLE_CONTEXT_SUMMARY: bool = True

    # ── Persistence ──────────────────────────────────────────────────────
    ENABLE_PERSISTENCE: bool = True
    DB_PATH: str = "data/conversations.db"

    # ── Search ───────────────────────────────────────────────────────────────
    SERPAPI_KEY: str = ""
    SERPAPI_ENGINE: str = "google"

    # ── Audio ─────────────────────────────────────────────────────────────────
    # Client sends raw PCM: 16-bit signed little-endian, 16 kHz, mono
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    AUDIO_SAMPLE_WIDTH: int = 2  # bytes (int16)
    # When True, every uploaded audio clip is saved as a WAV file under
    # SAVE_UPLOAD_AUDIO_DIR for later ASR analysis / debugging.
    SAVE_UPLOAD_AUDIO: bool = False
    SAVE_UPLOAD_AUDIO_DIR: str = "audio_logs"

    # ── Agent framework ───────────────────────────────────────────────────────
    AGENT_MAX_TOOL_ROUNDS: int = 5
    AGENT_ENABLE_TRACING: bool = True
    LLM_STREAMING: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
