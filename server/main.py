"""
Olivia Voice Assistant — FastAPI Server  (with Tool Calling)
=============================================================
WebSocket 协议 (文本帧 / 二进制帧):

  Client → Server:
    binary  : PCM audio chunk (16-bit, 16 kHz, mono)
    text    : "END"        — 录音结束，触发完整处理管道
    text    : "PING"       — 保活心跳

  Server → Client:
        text    : "USER_TEXT:<msg>"    — ASR 识别出的用户文本
        text    : "ASSISTANT_TEXT:<msg>" — 助手最终文本回复
    text    : "STATUS:<msg>"       — 工具调用状态提示（立即推送）
    text    : "STATUS_AUDIO_DONE"  — 状态提示音发送完毕（可选）
    binary  : MP3 audio chunk      — TTS 结果（分批流式）
    text    : "DONE"               — 本轮音频发送完毕
    text    : "EMPTY"              — 未识别到有效语音
    text    : "ERROR:<msg>"        — 处理异常
    text    : "PONG"               — 心跳回应
"""

import asyncio
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .asr.whisper_asr import WhisperASR
from .llm.openai_llm import OpenAILLM
from .llm.ollama_llm import OllamaLLM
from .tts.edge_tts_engine import EdgeTTSEngine
from .tts.sovits_tts import SovitsTTS
from .agent import ToolAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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


# ── Per-connection conversation history ───────────────────────────────────────
class Session:
    def __init__(self):
        self.history: list[dict] = []

    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        # Keep only the last N turns to bound token usage
        max_msgs = settings.MAX_HISTORY_TURNS * 2
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]

    def messages(self) -> list[dict]:
        return [{"role": "system", "content": settings.SYSTEM_PROMPT}] + self.history


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    client = websocket.client
    logger.info("Client connected: %s", client)

    session = Session()
    audio_buffer = io.BytesIO()

    # ── Status callback ───────────────────────────────────────────────────────
    # Called by ToolAgent the moment a tool starts executing.
    # Sends STATUS:<msg> immediately so the client can play a "hold on" prompt
    # without waiting for the full tool + LLM + TTS pipeline to finish.
    async def send_status(msg: str) -> None:
        try:
            logger.info("[STATUS] %s", msg)
            await websocket.send_text(f"STATUS:{msg}")
            # Optional: synthesize and push a short status audio clip so the
            # user hears voice feedback right away (requires TTS_STATUS_AUDIO=true).
            if settings.TTS_STATUS_AUDIO:
                async for chunk in tts.synthesize_stream(msg):
                    if chunk:
                        await websocket.send_bytes(chunk)
                await websocket.send_text("STATUS_AUDIO_DONE")
        except Exception:
            pass  # Never let status delivery crash the main pipeline

    try:
        while True:
            message = await websocket.receive()

            # ── Binary frame: incoming PCM audio chunk ────────────────────
            if "bytes" in message and message["bytes"]:
                audio_buffer.write(message["bytes"])

            # ── Text frame: control signal ────────────────────────────────
            elif "text" in message:
                cmd = message["text"].strip().upper()

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
                    await websocket.send_text("EMPTY")
                    continue

                try:
                    # 1. ASR
                    text = await asyncio.to_thread(asr.transcribe, raw_pcm)
                    logger.info("[ASR] %s", text)

                    if not text.strip():
                        await websocket.send_text("EMPTY")
                        continue

                    await websocket.send_text(f"USER_TEXT:{text}")

                    # 2. Agent: LLM intent detection + optional tool calls (non-blocking)
                    session.add("user", text)
                    agent = ToolAgent(llm_client=llm, status_cb=send_status)
                    reply = await agent.run(session.messages())
                    session.add("assistant", reply)
                    logger.info("[LLM/Agent] %s", reply)
                    await websocket.send_text(f"ASSISTANT_TEXT:{reply}")

                    # 3. TTS + 4. Return audio (streaming)
                    total_bytes = 0
                    async for chunk in tts.synthesize_stream(reply):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        await websocket.send_bytes(chunk)
                    logger.info("[TTS] streamed %d bytes", total_bytes)

                    await websocket.send_text("DONE")

                except Exception as exc:
                    logger.exception("Pipeline error")
                    await websocket.send_text(f"ERROR:{exc}")

    except WebSocketDisconnect:
        logger.info("Client disconnected: %s", client)
    except Exception:
        logger.exception("Unexpected WebSocket error")
    finally:
        audio_buffer.close()

# ── Web client (mobile browser) ───────────────────────────────────────────────
_WEB_CLIENT = Path(__file__).parent.parent / "web_client" / "index.html"

@app.get("/", include_in_schema=False)
async def web_app():
    """Serve the single-page mobile web client."""
    return FileResponse(_WEB_CLIENT, media_type="text/html")