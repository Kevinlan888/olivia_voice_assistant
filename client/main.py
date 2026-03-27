"""
Olivia Voice Assistant — Client Entry Point
============================================

Flow:
  1. Wait for wake word (offline, on-device)
  2. Play a brief acknowledgement beep
  3. Record the user's utterance (with VAD)
  4. Send audio to server over WebSocket
  5. Play back the server's TTS response
  6. Return to step 1
"""

import asyncio
import logging
import signal
import sys

from .config import settings
from .wake_word import WakeWordDetector
from .audio_recorder import AudioRecorder
from .audio_player import AudioPlayer
from .ws_client import WSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _play_beep(player: AudioPlayer) -> None:
    """Play a short 440 Hz MP3 beep to signal readiness.
    
    Generates a minimal WAV in memory using the standard library — no
    external audio asset required.
    """
    import math
    import struct
    import io
    import wave

    sample_rate = 22050
    duration = 0.15  # seconds
    freq = 880.0
    num_samples = int(sample_rate * duration)
    samples = [
        int(32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(num_samples)
    ]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"{num_samples}h", *samples))
    wav_bytes = buf.getvalue()

    # pygame can play WAV bytes too
    import pygame
    buf.seek(0)
    sound = pygame.mixer.Sound(buf)
    sound.play()
    import time
    time.sleep(duration + 0.05)


async def run() -> None:
    detector = WakeWordDetector() if settings.WAKE_WORD_KEYWORD.strip() else None
    recorder = AudioRecorder()
    player = AudioPlayer()

    # ── Status callbacks ──────────────────────────────────────────────────────
    # Called when the server starts executing a tool (before TTS is ready).
    # Using asyncio.to_thread so the blocking pygame.play() doesn't stall the loop.

    async def on_status(msg: str) -> None:
        """Log the status text (extend this to flash an LED, update a display, etc.)"""
        logger.info("⏳ %s", msg)

    async def on_status_audio(mp3_bytes: bytes) -> None:
        """Play the server-synthesised status audio clip immediately."""
        await asyncio.to_thread(player.play, mp3_bytes)

    async def on_audio_chunk(mp3_chunk: bytes) -> None:
        """Queue assistant audio chunk for progressive playback."""
        if settings.STREAM_PLAYBACK:
            await asyncio.to_thread(player.feed_stream_chunk, mp3_chunk)

    ws = WSClient(
        on_status=on_status,
        on_status_audio=on_status_audio,
        on_audio_chunk=on_audio_chunk,
    )

    if detector is None:
        logger.warning(
            "WAKE_WORD_KEYWORD is empty — skipping wake word, press Ctrl-C to quit."
        )

    # Pre-connect to reduce first-utterance latency
    await ws.connect()

    # Graceful shutdown on Ctrl-C.
    # On Windows, ProactorEventLoop may not implement add_signal_handler.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    signal_handlers_registered = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
            signal_handlers_registered = True
        except (NotImplementedError, RuntimeError):
            # RuntimeError can occur in non-main-thread contexts.
            signal_handlers_registered = False
            break

    try:
        while not stop_event.is_set():
            # ── Step 1: Wake word ────────────────────────────────────────────
            if detector:
                await asyncio.to_thread(detector.wait_for_wake_word)

            # ── Step 2: Acknowledgement beep ─────────────────────────────────
            await asyncio.to_thread(_play_beep, player)

            # ── Step 3: Record utterance ─────────────────────────────────────
            raw_pcm = await asyncio.to_thread(recorder.record)
            if not raw_pcm:
                continue

            # ── Step 4: Send to server, get TTS audio ────────────────────────
            if settings.STREAM_PLAYBACK:
                await asyncio.to_thread(player.start_stream)
            audio_response = await ws.process_audio(raw_pcm)
            if settings.STREAM_PLAYBACK:
                await asyncio.to_thread(player.stop_stream, True)

            # ── Step 5: Play response ────────────────────────────────────────
            if audio_response and not settings.STREAM_PLAYBACK:
                await asyncio.to_thread(player.play, audio_response)

            # Fallback for platforms without signal handler support.
            if not signal_handlers_registered:
                await asyncio.sleep(0)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down.")

    finally:
        await ws.disconnect()
        recorder.close()
        player.close()
        if detector:
            detector.close()
        logger.info("Olivia client stopped.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
