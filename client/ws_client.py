"""
Async WebSocket client.

Sends PCM audio to the server and receives MP3 audio back.
Handles chunked streaming and STATUS frames for tool-calling feedback.

New server signals handled here:
  STATUS:<msg>         — server is executing a tool; play status_audio if provided,
                         otherwise just log.  The server may optionally follow this
                         with binary audio chunks + STATUS_AUDIO_DONE.
  STATUS_AUDIO_DONE    — the short status-hint audio has finished; resume collecting
                         the final reply audio into a fresh buffer.
"""

import asyncio
import io
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
                   server sends a STATUS frame.  Use this to update a UI
                   indicator or emit a local beep on the client device.
        on_status_audio: Optional async callback(mp3_bytes: bytes) invoked
                         when the server pushes a synthesised status audio
                         clip (STATUS_AUDIO_DONE marks its end).  The client
                         should play this immediately so the user gets instant
                         voice feedback while tools are running.
    """

    def __init__(
        self,
        on_status=None,
        on_status_audio=None,
    ):
        self._url = settings.SERVER_WS_URL
        self._ws = None
        self._ping_task: asyncio.Task | None = None
        self._on_status = on_status
        self._on_status_audio = on_status_audio

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

    async def disconnect(self) -> None:
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        logger.info("Disconnected.")

    async def _keepalive(self) -> None:
        """Send PING every 20 s to prevent the server from closing the socket."""
        try:
            while True:
                await asyncio.sleep(20)
                if self._ws and not self._ws.closed:
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
        if self._ws is None or self._ws.closed:
            await self.connect()

        # 1. Stream audio in chunks
        for i in range(0, len(raw_pcm), _SEND_CHUNK):
            await self._ws.send(raw_pcm[i : i + _SEND_CHUNK])

        # 2. Signal end of audio
        await self._ws.send("END")
        logger.info("Sent audio (%d bytes), waiting for response …", len(raw_pcm))

        # 3. Collect response (binary = audio, text = control)
        audio_buf = io.BytesIO()
        status_audio_buf: io.BytesIO | None = None  # accumulates STATUS audio

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    # Bytes go into the active buffer:
                    #   - status_audio_buf while receiving a status clip
                    #   - audio_buf for the final reply
                    if status_audio_buf is not None:
                        status_audio_buf.write(message)
                    else:
                        audio_buf.write(message)

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
                        # Tool is running — notify upper layer immediately
                        status_text = message[7:]
                        logger.info("[STATUS] %s", status_text)
                        if self._on_status:
                            await self._on_status(status_text)
                        # Begin collecting possible status audio clip
                        status_audio_buf = io.BytesIO()

                    elif message == "STATUS_AUDIO_DONE":
                        # Server finished sending the status audio clip
                        if status_audio_buf is not None:
                            clip = status_audio_buf.getvalue()
                            status_audio_buf = None
                            if clip and self._on_status_audio:
                                await self._on_status_audio(clip)

                    elif message == "PONG":
                        pass  # ignore keepalive echo

        except ConnectionClosedError as exc:
            logger.warning("Connection closed unexpectedly: %s", exc)
            self._ws = None
            return None

        return audio_buf.getvalue() or None
