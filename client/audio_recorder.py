"""
Microphone recorder with Silero Voice Activity Detection (VAD).

Uses a lightweight ONNX neural-network model for robust speech detection,
far more accurate than energy-based approaches in noisy environments.
Runs on ONNX Runtime — no PyTorch needed, works great on Raspberry Pi.

Records until a configurable period of silence or a maximum duration,
then returns the raw PCM bytes (int16, 16 kHz, mono).
"""

import logging
import urllib.request
from pathlib import Path

import pyaudio
import numpy as np
import onnxruntime

from .audio_manager import manager
from .config import settings

logger = logging.getLogger(__name__)

_SILERO_VAD_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/"
    "src/silero_vad/data/silero_vad.onnx"
)


# ── Silero VAD (ONNX) singleton ─────────────────────────────────────────
class _SileroVAD:
    """Thin wrapper around the Silero VAD ONNX model."""

    def __init__(self, model_path: Path):
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = onnxruntime.InferenceSession(
            str(model_path), sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        # Detect model version from input names (v5 uses "state", v4 uses "h"/"c")
        input_names = {inp.name for inp in self._sess.get_inputs()}
        if "state" in input_names:
            self._version = 5
            self._state_shape = (2, 1, 128)
        else:
            self._version = 4
            self._state_shape = (2, 1, 64)
        self.reset_states()
        logger.info("Silero VAD ONNX model loaded (v%d)", self._version)

    def reset_states(self) -> None:
        if self._version == 5:
            self._state = np.zeros(self._state_shape, dtype=np.float32)
        else:
            self._h = np.zeros(self._state_shape, dtype=np.float32)
            self._c = np.zeros(self._state_shape, dtype=np.float32)

    def __call__(self, audio: np.ndarray, sample_rate: int) -> float:
        """Return speech probability (0.0–1.0) for a float32 audio chunk."""
        audio_2d = audio.reshape(1, -1).astype(np.float32)
        sr = np.array([sample_rate], dtype=np.int64)

        if self._version == 5:
            out, state_n = self._sess.run(
                ["output", "stateN"],
                {"input": audio_2d, "state": self._state, "sr": sr},
            )
            self._state = state_n
        else:
            out, hn, cn = self._sess.run(
                ["output", "hn", "cn"],
                {"input": audio_2d, "h": self._h, "c": self._c, "sr": sr},
            )
            self._h = hn
            self._c = cn

        return float(out.squeeze())


_vad_model: _SileroVAD | None = None


def _ensure_model_file() -> Path:
    """Download the Silero VAD ONNX model if not cached."""
    cache_dir = Path.home() / ".cache" / "silero-vad"
    model_path = cache_dir / "silero_vad.onnx"
    if not model_path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading Silero VAD ONNX model …")
        urllib.request.urlretrieve(_SILERO_VAD_URL, model_path)
        logger.info("Saved to %s", model_path)
    return model_path


def _load_vad_model() -> _SileroVAD:
    """Load and cache the Silero VAD ONNX model."""
    global _vad_model
    if _vad_model is None:
        _vad_model = _SileroVAD(_ensure_model_file())
    return _vad_model


def _speech_prob(chunk_bytes: bytes, sample_rate: int) -> float:
    """Return speech probability (0.0–1.0) for a raw int16 PCM chunk."""
    samples = np.frombuffer(chunk_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return _load_vad_model()(samples, sample_rate)


class AudioRecorder:
    """Capture one utterance from the microphone and return PCM bytes.

    Uses Silero VAD (neural-network based):
      - Recording starts immediately.
      - After the user stops speaking (speech probability stays below
        VAD_THRESHOLD for SILENCE_SECONDS), recording stops automatically.
      - Hard capped at MAX_RECORDING_SECONDS.
    """

    def __init__(self):
        self._rate = settings.SAMPLE_RATE
        self._chunk = settings.CHUNK_FRAMES
        self._vad_threshold = settings.VAD_THRESHOLD
        self._silence_limit = int(settings.SILENCE_SECONDS * self._rate / self._chunk)
        self._min_chunks = int(settings.MIN_RECORDING_SECONDS * self._rate / self._chunk)
        self._max_chunks = int(settings.MAX_RECORDING_SECONDS * self._rate / self._chunk)
        self._pre_stream = None
        # Pre-load VAD model so the first recording doesn't stall
        _load_vad_model()
        logger.info(
            "AudioRecorder ready: rate=%d vad_threshold=%.2f silence=%.1fs",
            self._rate, self._vad_threshold, settings.SILENCE_SECONDS,
        )

    def pre_open_stream(self) -> None:
        """Open the mic stream before the beep.

        Call this BEFORE playing the acknowledgement beep so there is no
        latency when record() starts consuming frames.

        record() will reuse the already-open stream and flush frames
        captured during the beep.
        """
        if self._pre_stream is not None:
            return  # already open
        pa = manager.get_pa()
        self._pre_stream = pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )
        logger.info("Pre-opened mic stream")

    def record(self) -> bytes:
        """Open the mic, record one utterance with Silero VAD, return raw PCM bytes."""
        # Reset VAD internal states for a fresh utterance
        _load_vad_model().reset_states()

        if self._pre_stream is not None:
            stream = self._pre_stream
            self._pre_stream = None
            # Flush ALL audio buffered while the stream was pre-open (covers
            # the beep duration + any PyAudio open latency).
            stale = stream.get_read_available()
            if stale > 0:
                stream.read(stale, exception_on_overflow=False)
                logger.debug("Flushed %d stale frames from pre-open stream", stale)
        else:
            pa = manager.get_pa()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=settings.CHANNELS,
                rate=self._rate,
                input=True,
                frames_per_buffer=self._chunk,
            )
            # Discard frames buffered during stream open (~100 ms).
            _flush = int(0.1 * self._rate / self._chunk)
            for _ in range(_flush):
                stream.read(self._chunk, exception_on_overflow=False)

        logger.info("Recording … (speak now)")

        frames: list[bytes] = []
        silent_chunks = 0
        total_chunks = 0
        speech_detected = False

        try:
            while total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1

                prob = _speech_prob(chunk, self._rate)

                if prob < self._vad_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                    speech_detected = True

                # Stop on sustained silence — but only after speech was detected
                # and the minimum recording duration has elapsed.
                if speech_detected and total_chunks >= self._min_chunks and silent_chunks >= self._silence_limit:
                    logger.info("Silence detected (Silero VAD, prob=%.2f) — stopping recording.", prob)
                    if silent_chunks <= len(frames):
                        frames = frames[: len(frames) - silent_chunks]
                    break
        finally:
            stream.stop_stream()
            stream.close()

        logger.info("Recorded %d chunks (%.1fs)", total_chunks, total_chunks * self._chunk / self._rate)
        return b"".join(frames)

    def record_ptt(self, button) -> bytes:
        """Record while the PTT button is held; stop when released.

        Args:
            button: PTTButton instance (already confirmed pressed before call).

        Returns raw PCM bytes (int16, mono, SAMPLE_RATE Hz).
        """
        pa = manager.get_pa()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )

        # Flush stale buffer.
        _flush = int(0.1 * self._rate / self._chunk)
        for _ in range(_flush):
            stream.read(self._chunk, exception_on_overflow=False)

        logger.info("PTT recording …")
        frames: list[bytes] = []
        total_chunks = 0

        try:
            while button.is_pressed() and total_chunks < self._max_chunks:
                chunk = stream.read(self._chunk, exception_on_overflow=False)
                frames.append(chunk)
                total_chunks += 1
        finally:
            stream.stop_stream()
            stream.close()

        logger.info("PTT released — recorded %d chunks (%.1fs)", total_chunks, total_chunks * self._chunk / self._rate)
        return b"".join(frames)

    def close(self) -> None:
        if self._pre_stream is not None:
            try:
                self._pre_stream.stop_stream()
                self._pre_stream.close()
            except Exception:
                pass
            self._pre_stream = None
