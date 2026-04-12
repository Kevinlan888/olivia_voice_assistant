"""
Async WebSocket client.

Sends PCM audio to the server and receives MP3 audio back.
Handles chunked streaming and STATUS frames for tool-calling feedback.

Supports both protocol v1 (plain text frames) and v2 (JSON events).
Protocol negotiation: after connecting, sends ``{"protocol": "v2"}``
and upgrades if the server acknowledges. Falls back to v1 otherwise.

v1 signals:
  STATUS:<msg>         — server is executing a tool
  STATUS_AUDIO_DONE    — status audio clip finished
  USER_TEXT:<msg>      — ASR result
  ASSISTANT_TEXT:<msg> — final LLM reply
  DONE / EMPTY / ERROR:<msg> / PONG

v2 JSON events:
  {"event": "status", "text": "..."}
  {"event": "user_text", "text": "..."}
  {"event": "assistant_text", "text": "...", "agent": "..."}
  {"event": "tool_start", "tool": "...", "args": {...}}
  {"event": "tool_end", "tool": "...", "result": "..."}
  {"event": "handoff", "from": "...", "to": "..."}
  {"event": "llm_token", "token": "..."}
  {"event": "agent_start", "agent": "..."}
  {"event": "agent_end", "agent": "..."}
  {"event": "audio_done"}
  {"event": "empty"}
  {"event": "error", "message": "..."}
"""

import asyncio
import io
import json
import logging
import websockets
from websockets.exceptions import ConnectionClosedError

from .config import settings

logger = logging.getLogger(__name__)

# How many PCM bytes to send per WebSocket binary frame
_SEND_CHUNK = 8192


class WSClient:
    """Manages a persistent WebSocket connection to the Olivia server.

    Args:
        on_status: Optional async callback(msg: str) invoked whenever the
                   server sends a STATUS frame.
        on_status_audio: Optional async callback(mp3_bytes: bytes) invoked
                         when the server pushes a synthesised status audio clip.
        on_audio_chunk: Optional async callback(mp3_bytes: bytes) invoked for
                        each audio chunk received.
        on_user_text: Optional async callback(text: str) invoked with ASR result.
        on_assistant_text: Optional async callback(text: str) invoked with LLM reply.
        on_llm_token: Optional async callback(token: str) invoked for each
                      streaming LLM token (v2 only).
        on_tool_start: Optional async callback(tool: str, args: dict) invoked
                       when a tool starts executing (v2 only).
        on_tool_end: Optional async callback(tool: str, result: str) invoked
                     when a tool finishes (v2 only).
        on_handoff: Optional async callback(from_agent: str, to_agent: str)
                    invoked when agent handoff occurs (v2 only).
    """

    def __init__(
        self,
        on_status=None,
        on_status_audio=None,
        on_audio_chunk=None,
        on_user_text=None,
        on_assistant_text=None,
        on_llm_token=None,
        on_tool_start=None,
        on_tool_end=None,
        on_handoff=None,
    ):
        self._url = settings.SERVER_WS_URL
        self._ws = None
        self._ping_task: asyncio.Task | None = None
        self._on_status = on_status
        self._on_status_audio = on_status_audio
        self._on_audio_chunk = on_audio_chunk
        self._on_user_text = on_user_text
        self._on_assistant_text = on_assistant_text
        self._on_llm_token = on_llm_token
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._on_handoff = on_handoff
        self._use_v2 = False

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self) -> None:
        logger.info("Connecting to %s …", self._url)
        self._ws = await websockets.connect(
            self._url,
            ping_interval=None,     # we manage keepalive ourselves
            max_size=10 * 1024 * 1024,  # 10 MB max message
        )
        self._ping_task = asyncio.create_task(self._keepalive())
        logger.info("Connected.")

        # Attempt v2 protocol upgrade
        try:
            await self._ws.send(json.dumps({"protocol": "v2"}))
            # Wait briefly for acknowledgement
            resp = await asyncio.wait_for(self._ws.recv(), timeout=2.0)
            if isinstance(resp, str):
                try:
                    data = json.loads(resp)
                    if data.get("protocol") == "v2" and data.get("status") == "ok":
                        self._use_v2 = True
                        logger.info("Upgraded to protocol v2")
                except json.JSONDecodeError:
                    pass
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("v2 upgrade failed, using v1: %s", exc)
            self._use_v2 = False

    def _is_connected(self) -> bool:
        """Compatibility check for websocket open state across websockets versions."""
        if self._ws is None:
            return False

        # websockets legacy protocol objects expose `.closed` (bool)
        closed = getattr(self._ws, "closed", None)
        if isinstance(closed, bool):
            return not closed

        # newer ClientConnection exposes `.state` enum-like values
        state = getattr(self._ws, "state", None)
        if state is not None:
            state_name = getattr(state, "name", str(state))
            return str(state_name).upper() == "OPEN"

        # If state cannot be determined, keep the existing connection.
        return True

    async def disconnect(self) -> None:
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        self._use_v2 = False
        logger.info("Disconnected.")

    async def _keepalive(self) -> None:
        """Send PING every 20 s to prevent the server from closing the socket."""
        try:
            while True:
                await asyncio.sleep(20)
                if self._is_connected():
                    await self._ws.send("PING")
        except asyncio.CancelledError:
            pass

    # ── Main pipeline ──────────────────────────────────────────────────────────

    async def process_audio(self, raw_pcm: bytes) -> bytes | None:
        """
        Send PCM audio to the server and collect the MP3 response.

        Returns:
            MP3 bytes on success, or None if the server returned EMPTY/ERROR.
        """
        if not self._is_connected():
            await self.connect()

        # 1. Stream audio in chunks
        for i in range(0, len(raw_pcm), _SEND_CHUNK):
            await self._ws.send(raw_pcm[i : i + _SEND_CHUNK])

        # 2. Signal end of audio
        await self._ws.send("END")
        logger.info("Sent audio (%d bytes), waiting for response …", len(raw_pcm))

        # 3. Collect response
        if self._use_v2:
            return await self._collect_v2()
        else:
            return await self._collect_v1()

    async def send_audio_chunk(self, chunk: bytes) -> None:
        """Send a single raw PCM chunk during a streaming upload.

        Called repeatedly while the microphone is still recording so that
        upload and recording proceed concurrently.  Must be followed by a
        call to :meth:`finish_upload` once recording is complete.
        """
        if not self._is_connected():
            await self.connect()
        await self._ws.send(chunk)

    async def finish_upload(self) -> bytes | None:
        """Signal end of audio and collect the server response.

        Call this after all chunks have been forwarded via
        :meth:`send_audio_chunk`.  Sends the END sentinel and then waits
        for the server's TTS audio reply, exactly like :meth:`process_audio`.

        Returns:
            MP3 bytes on success, or None if the server returned EMPTY/ERROR.
        """
        await self._ws.send("END")
        logger.info("Sent END (streaming upload complete), waiting for response …")
        if self._use_v2:
            return await self._collect_v2()
        else:
            return await self._collect_v1()

    # ── v2 response collection ────────────────────────────────────────────────

    async def _collect_v2(self) -> bytes | None:
        """Collect response using v2 JSON events."""
        audio_buf = io.BytesIO()

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    logger.info("Received audio chunk (%d bytes)", len(message))
                    audio_buf.write(message)
                    if self._on_audio_chunk:
                        await self._on_audio_chunk(message)

                elif isinstance(message, str):
                    # PONG is still plain text
                    if message == "PONG":
                        continue

                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON v2 frame: %s", message[:100])
                        continue

                    event = data.get("event")

                    if event == "audio_done":
                        logger.info("Response complete (%d bytes)", audio_buf.tell())
                        return audio_buf.getvalue()

                    elif event == "empty":
                        logger.info("Server: no speech detected.")
                        return None

                    elif event == "error":
                        logger.error("Server error: %s", data.get("message", ""))
                        return None

                    elif event == "user_text":
                        text = data.get("text", "")
                        logger.info("[ASR] %s", text)
                        if self._on_user_text:
                            await self._on_user_text(text)

                    elif event == "assistant_text":
                        text = data.get("text", "")
                        logger.info("[LLM] %s (agent=%s)", text, data.get("agent", ""))
                        if self._on_assistant_text:
                            await self._on_assistant_text(text)

                    elif event == "status":
                        text = data.get("text", "")
                        logger.info("[STATUS] %s", text)
                        if self._on_status:
                            await self._on_status(text)

                    elif event == "llm_token":
                        token = data.get("token", "")
                        if self._on_llm_token:
                            await self._on_llm_token(token)

                    elif event == "tool_start":
                        tool = data.get("tool", "")
                        args = data.get("args", {})
                        logger.info("[TOOL_START] %s %s", tool, args)
                        if self._on_tool_start:
                            await self._on_tool_start(tool, args)

                    elif event == "tool_end":
                        tool = data.get("tool", "")
                        result = data.get("result", "")
                        logger.info("[TOOL_END] %s", tool)
                        if self._on_tool_end:
                            await self._on_tool_end(tool, result)

                    elif event == "handoff":
                        from_agent = data.get("from", "")
                        to_agent = data.get("to", "")
                        logger.info("[HANDOFF] %s → %s", from_agent, to_agent)
                        if self._on_handoff:
                            await self._on_handoff(from_agent, to_agent)

                    elif event in ("agent_start", "agent_end", "guardrail"):
                        logger.debug("[%s] %s", event, data)

        except ConnectionClosedError as exc:
            logger.warning("Connection closed unexpectedly: %s", exc)
            self._ws = None
            return None

        return audio_buf.getvalue() or None

    # ── v1 response collection ────────────────────────────────────────────────

    async def _collect_v1(self) -> bytes | None:
        """Collect response using v1 plain-text frames."""
        audio_buf = io.BytesIO()
        status_audio_buf: io.BytesIO | None = None

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    if status_audio_buf is not None:
                        status_audio_buf.write(message)
                    else:
                        audio_buf.write(message)
                        if self._on_audio_chunk:
                            await self._on_audio_chunk(message)

                elif isinstance(message, str):
                    if message == "DONE":
                        logger.info("Response complete (%d bytes)", audio_buf.tell())
                        return audio_buf.getvalue()

                    elif message == "EMPTY":
                        logger.info("Server: no speech detected.")
                        return None

                    elif message.startswith("ERROR:"):
                        logger.error("Server error: %s", message[6:])
                        return None

                    elif message.startswith("STATUS:"):
                        status_text = message[7:]
                        logger.info("[STATUS] %s", status_text)
                        if self._on_status:
                            await self._on_status(status_text)
                        status_audio_buf = io.BytesIO()

                    elif message == "STATUS_AUDIO_DONE":
                        if status_audio_buf is not None:
                            clip = status_audio_buf.getvalue()
                            status_audio_buf = None
                            if clip and self._on_status_audio:
                                await self._on_status_audio(clip)

                    elif message == "PONG":
                        pass

                    elif message.startswith("USER_TEXT:"):
                        user_text = message[10:]
                        logger.info("[ASR] %s", user_text)
                        if self._on_user_text:
                            await self._on_user_text(user_text)

                    elif message.startswith("ASSISTANT_TEXT:"):
                        assistant_text = message[15:]
                        logger.info("[LLM] %s", assistant_text)
                        if self._on_assistant_text:
                            await self._on_assistant_text(assistant_text)

        except ConnectionClosedError as exc:
            logger.warning("Connection closed unexpectedly: %s", exc)
            self._ws = None
            return None

        return audio_buf.getvalue() or None
