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
from pathlib import Path

from .config import settings
from .audio_manager import manager
from .wake_word import WakeWordDetector
from .audio_recorder import AudioRecorder
from .audio_player import AudioPlayer
from .ws_client import WSClient
from .ptt_button import PTTButton

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


_WAKEUP_MP3 = Path(__file__).parent / "audios" / "wakeup.mp3"
_PENDING_MP3 = Path(__file__).parent / "audios" / "pending.mp3"


def _play_beep(player: AudioPlayer) -> None:
    """Play the wakeup acknowledgement sound (client/audios/wakeup.mp3).

    Uses manager.get_pa() (not fresh_pa()) so any pre-opened capture stream
    opened by the recorder remains valid after the beep finishes.
    """
    import miniaudio
    import pyaudio

    mp3_bytes = _WAKEUP_MP3.read_bytes()
    result = miniaudio.decode(
        mp3_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000,
    )
    pcm = bytes(result.samples)
    pa = manager.get_pa()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=24000,
        output=True,
    )
    try:
        stream.write(pcm)
    finally:
        stream.stop_stream()
        stream.close()


async def run() -> None:
    ptt_enabled = settings.PTT_GPIO_PIN >= 0
    ptt: PTTButton | None = None
    if ptt_enabled:
        try:
            ptt = PTTButton()
        except Exception as exc:
            logger.warning("PTT button unavailable (%s) — falling back to wake-word mode.", exc)
            ptt_enabled = False

    # PTT mode disables wake-word detection.
    detector = (
        None
        if ptt_enabled or not settings.WAKE_WORD_KEYWORD.strip()
        else WakeWordDetector()
    )
    recorder = AudioRecorder()
    player = AudioPlayer()

    # ── Status callbacks ──────────────────────────────────────────────────────
    # Called when the server starts executing a tool (before TTS is ready).
    # Using asyncio.to_thread so the blocking player.play() doesn't stall the loop.

    async def on_status(msg: str) -> None:
        """Log the status text and play the pending sound."""
        logger.info("⏳ %s", msg)
        await asyncio.to_thread(player.play_or_feed, _PENDING_MP3.read_bytes())

    async def on_tool_start(tool: str, args: dict) -> None:
        """Play pending sound when a tool/agent call starts (v2 only)."""
        logger.info("🔧 tool_start: %s", tool)
        await asyncio.to_thread(player.play_or_feed, _PENDING_MP3.read_bytes())

    async def on_status_audio(mp3_bytes: bytes) -> None:
        """Play the server-synthesised status audio clip immediately.

        If stream playback is active, feed into the existing stream so we
        don't kill the worker's PyAudio instance.
        """
        await asyncio.to_thread(player.play_or_feed, mp3_bytes)

    async def on_audio_chunk(mp3_chunk: bytes) -> None:
        """Queue assistant audio chunk for progressive playback."""
        if settings.STREAM_PLAYBACK:
            await asyncio.to_thread(player.feed_stream_chunk, mp3_chunk)

    ws = WSClient(
        on_status=on_status,
        on_status_audio=on_status_audio,
        on_audio_chunk=on_audio_chunk,
        on_tool_start=on_tool_start,
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

    def _on_signal():
        stop_event.set()
        if detector:
            detector.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
            signal_handlers_registered = True
        except (NotImplementedError, RuntimeError):
            # RuntimeError can occur in non-main-thread contexts.
            signal_handlers_registered = False
            break

    try:
        while not stop_event.is_set():
            # ── Step 1: Wake word / PTT ──────────────────────────────────────
            if ptt:
                # PTT mode: block until button pressed, then record until released.
                await asyncio.to_thread(ptt.wait_for_press)
                await asyncio.to_thread(_play_beep, player)
                raw_pcm = await asyncio.to_thread(recorder.record_ptt, ptt)
            else:
                if detector:
                    await asyncio.to_thread(detector.wait_for_wake_word)

                if stop_event.is_set():
                    break

                # ── Step 2: Pre-open mic, then play acknowledgement beep ──────
                # Pre-opening before the beep lets PyAudio start buffering audio
                # immediately.  record() will flush the frames captured during
                # the beep, so the user's first syllable is never lost.
                await asyncio.to_thread(recorder.pre_open_stream)
                await asyncio.to_thread(_play_beep, player)

                # ── Step 3: Record utterance with concurrent upload ───────────
                # Ensure the WebSocket is open before the recording thread
                # starts firing on_speech_chunk callbacks.
                if not ws._is_connected():
                    await ws.connect()

                def _on_speech_chunk(chunk: bytes) -> None:
                    """Called from the recorder thread for each chunk once speech
                    starts.  Submits an async send to the event loop and blocks
                    until it completes so chunks arrive in order."""
                    fut = asyncio.run_coroutine_threadsafe(
                        ws.send_audio_chunk(chunk), loop
                    )
                    try:
                        fut.result(timeout=1.0)
                    except Exception as exc:
                        logger.warning("Failed to send audio chunk: %s", exc)

                raw_pcm = await asyncio.to_thread(recorder.record_streaming, _on_speech_chunk)
            if not raw_pcm:
                continue

            # ── Step 4: Finish upload and collect server response ─────────────
            # PTT path: audio was not streamed, send it now via process_audio.
            # Wake-word path: chunks were already uploaded; just send END.
            if settings.STREAM_PLAYBACK:
                await asyncio.to_thread(player.start_stream)
            if ptt:
                audio_response = await ws.process_audio(raw_pcm)
            else:
                audio_response = await ws.finish_upload()
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
        if ptt:
            ptt.close()
        manager.terminate_pa()
        logger.info("Olivia client stopped.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
