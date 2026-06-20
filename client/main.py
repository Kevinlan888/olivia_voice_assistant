"""
Olivia Voice Assistant — Client Entry Point
============================================

State machine flow:
  idle → (wake word / PTT) → recording → waiting_response → idle

The SharedMicrophone is the single owner of the input stream.
WakeWordDetector and AudioRecorder consume PCM chunks supplied by
the main loop — neither opens its own microphone stream.
"""

import asyncio
import collections
import logging
import signal
import sys
from pathlib import Path

from .config import settings
from .audio_manager import manager
from .shared_microphone import SharedMicrophone
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


def _request_shutdown(
    stop_event: asyncio.Event,
    run_task: asyncio.Task | None,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Request shutdown from a signal handler or fallback path."""
    stop_event.set()
    if run_task is not None and not run_task.done():
        run_task.cancel()


def _play_beep(player: AudioPlayer) -> None:
    """Play the wakeup acknowledgement sound (client/audios/wakeup.mp3).

    Uses manager.get_pa() so any pre-opened capture stream
    opened by SharedMicrophone remains valid after the beep finishes.
    """
    import miniaudio
    import pyaudio

    rate = settings.PLAYBACK_SAMPLE_RATE

    mp3_bytes = _WAKEUP_MP3.read_bytes()
    result = miniaudio.decode(
        mp3_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=rate,
    )
    pcm = bytes(result.samples)
    pa = manager.get_pa()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=rate,
        output=True,
    )
    try:
        stream.write(pcm)
    finally:
        stream.stop_stream()
        stream.close()


async def run() -> None:
    # ── PTT setup ─────────────────────────────────────────────────────
    ptt_enabled = settings.PTT_GPIO_PIN >= 0
    ptt: PTTButton | None = None
    if ptt_enabled:
        try:
            ptt = PTTButton()
        except Exception as exc:
            logger.warning("PTT button unavailable (%s) — falling back to wake-word mode.", exc)
            ptt_enabled = False

    # ── Component initialization ───────────────────────────────────────
    # PTT mode disables wake-word detection.
    detector = (
        None
        if ptt_enabled or not settings.WAKE_WORD_KEYWORD.strip()
        else WakeWordDetector()
    )

    if detector is None and not ptt_enabled:
        logger.warning(
            "WAKE_WORD_KEYWORD is empty — skipping wake word, press Ctrl-C to quit."
        )

    mic = SharedMicrophone()

    # ── Speech-chunk callback (for streaming upload, wake-word mode only) ─
    # PTT mode sends audio in one batch via ws.process_audio() after
    # recording finishes — the on_speech_chunk callback should NOT be
    # used for PTT, matching the original behavior.
    loop = asyncio.get_running_loop()
    speech_chunk_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_speech_chunk(chunk: bytes) -> None:
        """Called from the recorder for each chunk once speech starts.

        The recorder runs inside the main event-loop thread, so this
        callback must stay non-blocking. Chunks are queued here and
        drained asynchronously by the main loop to preserve order.
        """
        speech_chunk_queue.put_nowait(chunk)

    async def _flush_speech_chunk_queue() -> None:
        """Send any queued speech chunks to the server in FIFO order."""
        while not speech_chunk_queue.empty():
            chunk = await speech_chunk_queue.get()
            try:
                await ws.send_audio_chunk(chunk)
            except Exception as exc:
                logger.warning(
                    "Failed to send audio chunk (%s): %r",
                    type(exc).__name__,
                    exc,
                )

    recorder = AudioRecorder(
        on_speech_chunk=None if ptt_enabled else _on_speech_chunk,
    )
    player = AudioPlayer()

    # ── Status callbacks ──────────────────────────────────────────────
    async def on_status(msg: str) -> None:
        """Log the status text and play the pending sound."""
        logger.info("⏳ %s", msg)
        await asyncio.to_thread(player.play_or_feed, _PENDING_MP3.read_bytes())

    async def on_tool_start(tool: str, args: dict) -> None:
        """Play pending sound when a tool/agent call starts (v2 only)."""
        logger.info("🔧 tool_start: %s", tool)
        await asyncio.to_thread(player.play_or_feed, _PENDING_MP3.read_bytes())

    async def on_status_audio(mp3_bytes: bytes) -> None:
        """Play the server-synthesised status audio clip immediately."""
        await asyncio.to_thread(player.play_or_feed, mp3_bytes)

    async def on_audio_chunk(mp3_chunk: bytes) -> None:
        """Queue assistant audio chunk for progressive playback."""
        if settings.STREAM_PLAYBACK:
            if not player.is_streaming:
                await asyncio.to_thread(player.start_stream)
            await asyncio.to_thread(player.feed_stream_chunk, mp3_chunk)

    ws = WSClient(
        on_status=on_status,
        on_status_audio=on_status_audio,
        on_audio_chunk=on_audio_chunk,
        on_tool_start=on_tool_start,
    )

    # Pre-connect to reduce first-utterance latency
    await ws.connect()

    # ── Graceful shutdown ──────────────────────────────────────────────
    stop_event = asyncio.Event()
    signal_handlers_registered = False
    run_task = asyncio.current_task()

    def _on_signal():
        _request_shutdown(stop_event, run_task, loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
            signal_handlers_registered = True
        except (NotImplementedError, RuntimeError):
            signal_handlers_registered = False
            break

    # ── Prebuffer ─────────────────────────────────────────────────────
    prebuffer_maxlen = int(
        settings.WAKE_WORD_PREBUFFER_SECONDS * settings.SAMPLE_RATE / settings.CHUNK_FRAMES
    )
    prebuffer: collections.deque[bytes] = collections.deque(maxlen=prebuffer_maxlen)

    # ── Cooldown counter (chunk-count, not wall-clock) ────────────────
    cooldown_chunks = 0

    # ── State machine ─────────────────────────────────────────────────
    state = "idle"

    def _reset_to_idle() -> None:
        """Reset per-utterance state and return to idle."""
        nonlocal state, cooldown_chunks
        state = "idle"
        cooldown_chunks = int(
            settings.WAKE_WORD_COOLDOWN_SECONDS * settings.SAMPLE_RATE / settings.CHUNK_FRAMES
        )
        prebuffer.clear()

    try:
        for chunk in mic:
            if stop_event.is_set():
                break

            # ── idle ───────────────────────────────────────────────────
            if state == "idle":
                if cooldown_chunks > 0:
                    cooldown_chunks -= 1
                    # Still append to prebuffer during cooldown
                    prebuffer.append(chunk)
                    continue

                prebuffer.append(chunk)

                # PTT entry
                if ptt and ptt.is_pressed():
                    if not ws._is_connected():
                        await ws.connect()
                    await asyncio.to_thread(_play_beep, player)
                    recorder.start_utterance([])
                    state = "recording"
                    continue

                # Wake word detection
                if detector and detector.process_chunk(chunk):
                    logger.info("Wake word detected → transitioning to recording")
                    if not ws._is_connected():
                        await ws.connect()
                    # Play beep concurrently with recording
                    beep_task = asyncio.create_task(asyncio.to_thread(_play_beep, player))
                    recorder.start_utterance(list(prebuffer))
                    state = "recording"
                    continue

            # ── recording ──────────────────────────────────────────────
            elif state == "recording":
                # PTT: stop recording when button is released
                if ptt and not ptt.is_pressed():
                    pcm = recorder.finish_utterance()

                    if pcm is None:
                        logger.info("Empty PTT utterance — returning to idle")
                        _reset_to_idle()
                        continue

                    # PTT: send complete audio in one batch
                    if not ws._is_connected():
                        await ws.connect()
                    audio_response = await ws.process_audio(pcm)

                    if settings.STREAM_PLAYBACK:
                        await asyncio.to_thread(player.stop_stream, True)
                    if audio_response and not settings.STREAM_PLAYBACK:
                        await asyncio.to_thread(player.play, audio_response)

                    _reset_to_idle()
                    continue

                done = recorder.append_chunk(chunk)
                if not ptt_enabled:
                    await _flush_speech_chunk_queue()

                if done:
                    pcm = recorder.finish_utterance()

                    if pcm is None:
                        # No speech detected — discard and return to idle
                        logger.info("Empty utterance — returning to idle")
                        _reset_to_idle()
                        continue

                    # Wake-word mode: streaming upload already sent chunks,
                    # just send END and collect response
                    await _flush_speech_chunk_queue()
                    audio_response = await ws.finish_upload()

                    if settings.STREAM_PLAYBACK:
                        await asyncio.to_thread(player.stop_stream, True)

                    if audio_response and not settings.STREAM_PLAYBACK:
                        await asyncio.to_thread(player.play, audio_response)

                    _reset_to_idle()

            # ── waiting_response is implicit: finish_upload blocks until
            #    the server response is complete, so we transition directly
            #    from recording → idle after collecting the response.

            # Fallback for platforms without signal handler support.
            if not signal_handlers_registered:
                await asyncio.sleep(0)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Keyboard interrupt received, shutting down.")

    finally:
        mic.close()
        recorder.close()
        if detector:
            detector.close()
        player.close()
        if ptt:
            ptt.close()
        await ws.disconnect()
        manager.terminate_pa()
        logger.info("Olivia client stopped.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
