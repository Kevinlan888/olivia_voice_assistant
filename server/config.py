from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # ── ASR ──────────────────────────────────────────────────────────────────
    WHISPER_MODEL: str = "base"          # tiny / base / small / medium / large-v3
    WHISPER_DEVICE: str = "cpu"          # cpu / cuda
    WHISPER_COMPUTE_TYPE: str = "int8"   # int8 / float16 / float32

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
        "你是 Olivia，一个友好、简洁的语音助手。"
        "用简短的口语化中文回答，不使用 Markdown 格式。"
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
