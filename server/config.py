from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # ── ASR ──────────────────────────────────────────────────────────────────
    WHISPER_MODEL: str = "base"          # tiny / base / small / medium / large-v3
    WHISPER_DEVICE: str = "cpu"          # cpu / cuda
    WHISPER_COMPUTE_TYPE: str = "int8"   # int8 / float16 / float32

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
    MAX_HISTORY_TURNS: int = 10

    # ── Search ───────────────────────────────────────────────────────────────
    SERPAPI_KEY: str = ""
    SERPAPI_ENGINE: str = "google"

    # ── Audio ─────────────────────────────────────────────────────────────────
    # Client sends raw PCM: 16-bit signed little-endian, 16 kHz, mono
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    AUDIO_SAMPLE_WIDTH: int = 2  # bytes (int16)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
