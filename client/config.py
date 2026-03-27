from pydantic_settings import BaseSettings


class ClientSettings(BaseSettings):
    # ── Server connection ─────────────────────────────────────────────────────
    SERVER_WS_URL: str = "ws://localhost:8000/ws/audio"

    # ── Wake word (openWakeWord) ──────────────────────────────────────────────
    # Built-in model names include: "alexa", "hey mycroft", "hey jarvis", etc.
    # Set to empty string to disable wake-word gating.
    WAKE_WORD_KEYWORD: str = "alexa"
    WAKE_WORD_THRESHOLD: float = 0.5

    # ── Audio recording ───────────────────────────────────────────────────────
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1
    CHUNK_FRAMES: int = 512             # frames per PyAudio buffer read
    # Silence detection
    SILENCE_THRESHOLD: float = 300.0    # RMS energy below this = silence
    SILENCE_SECONDS: float = 1.5        # silence duration before stopping recording
    MAX_RECORDING_SECONDS: float = 15.0 # hard cap per utterance

    # ── Playback ──────────────────────────────────────────────────────────────
    PLAYBACK_DEVICE_INDEX: int = -1     # -1 = system default

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = ClientSettings()
