"""
Olivia Voice Assistant — FastAPI Server  (v2: Agent Framework + Streaming)
==========================================================================
WebSocket 协议:

  v1 (legacy, plain text frames)
  ─────────────────────────────
  Client → Server:
    binary  : PCM audio chunk (16-bit, 16 kHz, mono)
    text    : "END"        — 录音结束，触发完整处理管道
    text    : "PING"       — 保活心跳

  Server → Client:
    text    : "USER_TEXT:<msg>"      — ASR 识别出的用户文本
    text    : "ASSISTANT_TEXT:<msg>" — 助手最终文本回复
    text    : "STATUS:<msg>"         — 工具调用状态提示（立即推送）
    text    : "STATUS_AUDIO_DONE"    — 状态提示音发送完毕（可选）
    binary  : MP3 audio chunk        — TTS 结果（分批流式）
    text    : "DONE"                 — 本轮音频发送完毕
    text    : "EMPTY"                — 未识别到有效语音
    text    : "ERROR:<msg>"          — 处理异常
    text    : "PONG"                 — 心跳回应

  v2 (JSON events — client sends {"protocol": "v2"} as first frame)
  ─────────────────────────────────────────────────────────────────
  Server → Client text: JSON events (see protocol.py)
  Server → Client binary: MP3 audio chunks (unchanged)
  Client → Server: unchanged (binary PCM + text "END"/"PING")
"""

import asyncio
import io
import json
import logging
import os
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .asr.whisper_asr import WhisperASR
from .llm.openai_llm import OpenAILLM
from .llm.ollama_llm import OllamaLLM
from .tts.edge_tts_engine import EdgeTTSEngine
from .tts.sovits_tts import SovitsTTS
from .agent_framework import RunContext, Runner, EventEmitter
from .agent_framework import events as ev
from .agent_framework.sentence_splitter import SentenceSplitter
from .agents import create_router_agent
from .protocol import event_to_v1, event_to_v2, is_v2_handshake

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _save_audio(raw_pcm: bytes) -> None:
    """Save raw PCM bytes as a WAV file under settings.SAVE_UPLOAD_AUDIO_DIR."""
    try:
        out_dir = Path(settings.SAVE_UPLOAD_AUDIO_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = out_dir / f"{timestamp}.wav"
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(settings.AUDIO_CHANNELS)
            wf.setsampwidth(settings.AUDIO_SAMPLE_WIDTH)
            wf.setframerate(settings.AUDIO_SAMPLE_RATE)
            wf.writeframes(raw_pcm)
        logger.info("[SAVE_AUDIO] %s", out_path)
    except Exception as exc:
        logger.warning("[SAVE_AUDIO] Failed to save audio: %s", exc)


# ── Component singletons (initialised once at startup) ────────────────────────
asr: WhisperASR
llm: OpenAILLM | OllamaLLM
tts: EdgeTTSEngine | SovitsTTS


@asynccontextmanager
async def lifespan(app: FastAPI):
    global asr, llm, tts
    logger.info("Loading ASR model …")
    asr = await asyncio.to_thread(WhisperASR)

    logger.info(f"LLM provider: {settings.LLM_PROVIDER}")
    llm = await asyncio.to_thread(OpenAILLM if settings.LLM_PROVIDER == "openai" else OllamaLLM)

    logger.info(f"TTS provider: {settings.TTS_PROVIDER}")
    tts = await asyncio.to_thread(EdgeTTSEngine if settings.TTS_PROVIDER == "edge" else SovitsTTS)

    logger.info("Olivia server ready.")
    yield
    logger.info("Server shutting down.")


app = FastAPI(title="Olivia Voice Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    client = websocket.client
    logger.info("Client connected: %s", client)

    # Per-connection state
    ctx = RunContext(now=datetime.now(timezone.utc).astimezone())
    audio_buffer = io.BytesIO()
    use_v2 = False  # protocol version flag

    # Build the multi-agent graph once per connection
    root_agent = create_router_agent()

    try:
        while True:
            message = await websocket.receive()

            # ── Binary frame: incoming PCM audio chunk ────────────────────
            if "bytes" in message and message["bytes"]:
                audio_buffer.write(message["bytes"])

            # ── Text frame: control signal ────────────────────────────────
            elif "text" in message:
                text = message["text"].strip()

                # Protocol negotiation
                if is_v2_handshake(text):
                    use_v2 = True
                    await websocket.send_text(json.dumps({"protocol": "v2", "status": "ok"}))
                    logger.info("Client upgraded to protocol v2")
                    continue

                cmd = text.upper()

                if cmd == "PING":
                    await websocket.send_text("PONG")
                    continue

                if cmd != "END":
                    logger.warning("Unknown command: %s", cmd)
                    continue

                # ── Run pipeline ──────────────────────────────────────────
                raw_pcm = audio_buffer.getvalue()
                audio_buffer = io.BytesIO()  # reset for next turn

                if not raw_pcm:
                    if use_v2:
                        await websocket.send_text(json.dumps({"event": "empty"}))
                    else:
                        await websocket.send_text("EMPTY")
                    continue

                try:
                    await _run_pipeline(
                        websocket=websocket,
                        raw_pcm=raw_pcm,
                        ctx=ctx,
                        root_agent=root_agent,
                        use_v2=use_v2,
                    )
                except Exception as exc:
                    logger.exception("Pipeline error")
                    if use_v2:
                        await websocket.send_text(json.dumps({"event": "error", "message": str(exc)}))
                    else:
                        await websocket.send_text(f"ERROR:{exc}")

    except WebSocketDisconnect:
        logger.info("Client disconnected: %s", client)
    except Exception:
        logger.exception("Unexpected WebSocket error")
    finally:
        audio_buffer.close()


async def _run_pipeline(
    *,
    websocket: WebSocket,
    raw_pcm: bytes,
    ctx: RunContext,
    root_agent,
    use_v2: bool,
) -> None:
    """Execute the full ASR → Agent → TTS pipeline for one utterance."""

    # 0. Optionally persist the raw audio
    if settings.SAVE_UPLOAD_AUDIO:
        _save_audio(raw_pcm)

    # 1. ASR
    text = await asyncio.to_thread(asr.transcribe, raw_pcm)
    logger.info("[ASR] %s", text)

    if not text.strip():
        if use_v2:
            await websocket.send_text(json.dumps({"event": "empty"}))
        else:
            await websocket.send_text("EMPTY")
        return

    # Send user text
    if use_v2:
        await websocket.send_text(json.dumps({"event": "user_text", "text": text}))
    else:
        await websocket.send_text(f"USER_TEXT:{text}")

    # 2. Agent: LLM intent detection + tool calls + handoffs
    ctx.add_message("user", text)
    ctx.now = datetime.now(timezone.utc).astimezone()  # refresh time each turn

    # Set up event emitter → WebSocket bridge
    emitter = EventEmitter()

    async def _ws_event_listener(event: ev.Event) -> None:
        """Push framework events to WebSocket in real-time."""
        if use_v2:
            frame = event_to_v2(event)
            if frame:
                await websocket.send_text(frame)
        else:
            # v1: only push STATUS messages
            frame = event_to_v1(event)
            if frame:
                await websocket.send_text(frame)

            # v1: synthesize status audio for StatusMessage events
            if isinstance(event, ev.StatusMessage) and settings.TTS_STATUS_AUDIO:
                try:
                    async for chunk in tts.synthesize_stream(event.text):
                        if chunk:
                            await websocket.send_bytes(chunk)
                except Exception as exc:
                    logger.warning("Status audio synthesis failed: %s", exc)
                finally:
                    try:
                        await websocket.send_text("STATUS_AUDIO_DONE")
                    except Exception:
                        pass

    emitter.on(_ws_event_listener)

    runner = Runner(
        llm_client=llm,
        emitter=emitter,
        max_tool_rounds=settings.AGENT_MAX_TOOL_ROUNDS,
        enable_tracing=settings.AGENT_ENABLE_TRACING,
    )

    result = await runner.run(root_agent, ctx)
    reply = result.output

    ctx.add_message("assistant", reply)
    ctx.trim_history(settings.MAX_HISTORY_TURNS)

    logger.info("[Agent] %s (via %s)", reply, result.agent_name)

    # Send assistant text
    if use_v2:
        await websocket.send_text(json.dumps({"event": "assistant_text", "text": reply, "agent": result.agent_name}))
    else:
        await websocket.send_text(f"ASSISTANT_TEXT:{reply}")

    # 3. TTS → stream audio
    total_bytes = 0
    async for chunk in tts.synthesize_stream(reply):
        if not chunk:
            continue
        total_bytes += len(chunk)
        await websocket.send_bytes(chunk)
    logger.info("[TTS] streamed %d bytes", total_bytes)

    if use_v2:
        await websocket.send_text(json.dumps({"event": "audio_done"}))
    else:
        await websocket.send_text("DONE")

# ── Web client (Vue SPA built with Vite) ─────────────────────────────────────
_DIST = Path(__file__).parent.parent / "web_client" / "dist"

# Mount /assets → dist/assets so Vite's hashed JS/CSS bundles are served.
# This is set up at module load time; run `cd web_client && npm run build` first.
_assets_dir = _DIST / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static_assets")


@app.get("/", include_in_schema=False)
async def web_app():
    """Serve the Vue SPA entry point."""
    idx = _DIST / "index.html"
    if not idx.exists():
        return FileResponse(
            Path(__file__).parent.parent / "web_client" / "index.html",
            media_type="text/html",
        )
    return FileResponse(idx, media_type="text/html")