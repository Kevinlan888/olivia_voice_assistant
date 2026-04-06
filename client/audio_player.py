"""
Audio player using miniaudio for MP3 decoding and PyAudio for output.

Streaming playback writes decoded PCM to a single continuous PyAudio output
stream — analogous to the web client's MediaSource + SourceBuffer approach —
eliminating the inter-segment gaps that plague load→play→load cycles.

miniaudio decodes MP3 entirely in memory without touching an audio device,
so there is no device-ownership conflict with the capture streams.
"""

import logging
import pyaudio
import queue
import threading
import miniaudio

from .audio_manager import manager
from .config import settings

logger = logging.getLogger(__name__)


# Output parameters — must match what edge-tts produces (24 kHz mono int16).
_OUT_RATE = 24000
_OUT_CHANNELS = 1


def _decode_mp3(mp3_bytes: bytes) -> bytes:
    """Decode MP3 bytes to raw int16 PCM using miniaudio (no audio device needed)."""
    result = miniaudio.decode(
        mp3_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=_OUT_CHANNELS,
        sample_rate=_OUT_RATE,
    )
    return bytes(result.samples)


class AudioPlayer:
    """Thread-safe audio player with gapless streaming support."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stream_queue: queue.Queue[bytes | None] | None = None
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()
        logger.info("AudioPlayer ready (miniaudio decoder + pyaudio output)")

    def play(self, mp3_bytes: bytes) -> None:
        """Decode MP3 and play synchronously via PyAudio (blocks until done)."""
        with self._lock:
            pcm = _decode_mp3(mp3_bytes)
            pa = manager.fresh_pa()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=_OUT_CHANNELS,
                rate=_OUT_RATE,
                output=True,
            )
            try:
                stream.write(pcm)
            finally:
                stream.stop_stream()
                stream.close()

    def stop(self) -> None:
        self._stream_stop.set()

    def start_stream(self) -> None:
        """Start a background worker that plays incoming MP3 chunks seamlessly."""
        self.stop_stream(wait=True)
        self._stream_stop.clear()
        self._stream_queue = queue.Queue()
        self._stream_thread = threading.Thread(target=self._stream_worker, daemon=True)
        self._stream_thread.start()

    def feed_stream_chunk(self, chunk: bytes) -> None:
        """Queue one MP3 chunk for streaming playback."""
        if not chunk:
            return
        if self._stream_queue is not None:
            self._stream_queue.put(chunk)

    def stop_stream(self, wait: bool = True) -> None:
        """Signal the stream worker to finish and optionally wait.

        When *wait* is True the worker will flush all remaining buffered
        audio before exiting (graceful drain).  The hard-abort flag
        ``_stream_stop`` is only set when *wait* is False (or via ``stop()``).
        """
        if self._stream_queue is not None:
            self._stream_queue.put(None)
        if not wait:
            self._stream_stop.set()
        if wait and self._stream_thread is not None:
            self._stream_thread.join(timeout=30)
        self._stream_queue = None
        self._stream_thread = None

    # ── Buffering thresholds ─────────────────────────────────────────────────
    # We accumulate ALL incoming MP3 bytes into a single growing buffer and
    # re-decode the *entire* stream each time via miniaudio.decode().  Only
    # the newly decoded PCM (delta) is appended to a ring buffer that a
    # PyAudio callback drains continuously.  This mirrors the web client's
    # MediaSource approach: one logical decoder session, zero inter-segment
    # gaps, and the audio callback guarantees the output device never starves.
    _INITIAL_BUF = 12_288   # MP3 bytes before first decode (~0.4-0.8 s)

    def _stream_worker(self) -> None:
        q = self._stream_queue
        if q is None:
            return

        pa = manager.fresh_pa()

        freq = _OUT_RATE
        channels = _OUT_CHANNELS

        # ── PCM ring buffer shared between decoder and audio callback ─────
        pcm_ring = bytearray()
        ring_lock = threading.Lock()

        def _audio_callback(in_data, frame_count, time_info, status):
            """PyAudio calls this from a dedicated real-time thread."""
            needed = frame_count * 2 * channels          # 16-bit samples
            with ring_lock:
                avail = len(pcm_ring)
                if avail >= needed:
                    data = bytes(pcm_ring[:needed])
                    del pcm_ring[:needed]
                else:
                    # Under-run: output what we have + pad with silence
                    data = bytes(pcm_ring) + b'\x00' * (needed - avail)
                    pcm_ring.clear()
            return (data, pyaudio.paContinue)

        try:
            out = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=freq,
                output=True,
                frames_per_buffer=2048,
                stream_callback=_audio_callback,
            )
        except Exception:
            manager.ensure_mixer()
            raise
        out.start_stream()

        all_mp3 = bytearray()      # complete MP3 bitstream received so far
        pcm_written = 0             # PCM bytes already pushed to ring buffer

        def _decode_delta() -> None:
            """Re-decode the full MP3 stream; push only new PCM to the ring."""
            nonlocal pcm_written
            try:
                pcm = _decode_mp3(bytes(all_mp3))
                new_pcm = pcm[pcm_written:]
                if new_pcm:
                    with ring_lock:
                        pcm_ring.extend(new_pcm)
                    pcm_written += len(new_pcm)
            except Exception as exc:
                logger.warning("Stream decode error: %s", exc)

        try:
            while not self._stream_stop.is_set():
                timeout = 0.5 if pcm_written == 0 else 0.08
                try:
                    chunk = q.get(timeout=timeout)
                except queue.Empty:
                    # Timeout — flush whatever MP3 we have so far
                    if all_mp3 and pcm_written == 0:
                        _decode_delta()
                    continue

                if chunk is None:
                    # Stream finished — final decode
                    if all_mp3:
                        _decode_delta()
                    break

                all_mp3.extend(chunk)

                # Wait for enough data before the very first decode
                if pcm_written == 0 and len(all_mp3) < self._INITIAL_BUF:
                    continue

                _decode_delta()

            # ── Drain: wait for the ring buffer to be fully played ────────
            while not self._stream_stop.is_set():
                with ring_lock:
                    remaining = len(pcm_ring)
                if remaining == 0:
                    break
                threading.Event().wait(0.05)

        finally:
            try:
                out.stop_stream()
                out.close()
            except Exception:
                pass

    def close(self) -> None:
        self.stop_stream(wait=False)
