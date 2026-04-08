import os
import sys
from pydantic_settings import BaseSettings


def _env_file_path() -> str:
    """Resolve .env path for both normal runs and PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts --add-data files into sys._MEIPASS
        return os.path.join(sys._MEIPASS, ".env")
    return ".env"


class ClientSettings(BaseSettings):
    # ── Server connection ─────────────────────────────────────────────────────
    SERVER_WS_URL: str = "ws://localhost:8000/ws/audio"

    # ── Wake word (Porcupine / Picovoice) ────────────────────────────────────
    # Obtain a free access key at https://console.picovoice.ai/
    PICOVOICE_ACCESS_KEY: str = ""
    # Built-in keywords: alexa, americano, blueberry, bumblebee, computer,
    #   grapefruit, grasshopper, hey google, hey siri, jarvis, ok google,
    #   picovoice, porcupine, terminator
    # Set to empty string to use WAKE_WORD_KEYWORD_PATH instead.
    WAKE_WORD_KEYWORD: str = "porcupine"
    # Optional path to a custom .ppn keyword file; takes precedence over WAKE_WORD_KEYWORD.
    WAKE_WORD_KEYWORD_PATH: str = ""
    WAKE_WORD_THRESHOLD: float = 0.5      # sensitivity 0.0–1.0 (higher = more sensitive)
    WAKE_WORD_COOLDOWN_SECONDS: float = 1.0  # ignore immediate retriggers after detection

    # ── Audio recording ───────────────────────────────────────────────────────
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1
    CHUNK_FRAMES: int = 512             # frames per PyAudio buffer read
    # Silero VAD (neural-network voice activity detection)
    SILERO_SPEECH_THRESHOLD: float = 0.5  # prob ≥ this = speech (0.0–1.0)
    SILENCE_SECONDS: float = 0.8        # silence duration before stopping recording
    MIN_RECORDING_SECONDS: float = 1.0  # minimum recording duration before VAD can stop
    MAX_RECORDING_SECONDS: float = 15.0 # hard cap per utterance

    # ── Push-to-talk button (Raspberry Pi GPIO) ───────────────────────────────
    # Set PTT_GPIO_PIN to a BCM pin number to enable push-to-talk mode.
    # While enabled, wake-word detection is bypassed: hold button → record,
    # release → stop.  Set to -1 (default) to disable.
    PTT_GPIO_PIN: int = -1              # BCM pin, e.g. 17; -1 = disabled
    PTT_PULL_UP: bool = True            # True = pull-up (button connects to GND)

    # ── Playback ──────────────────────────────────────────────────────────────
    PLAYBACK_DEVICE_INDEX: int = -1     # -1 = system default
    STREAM_PLAYBACK: bool = True         # play assistant audio progressively

    class Config:
        env_file = _env_file_path()
        extra = "ignore"


settings = ClientSettings()
