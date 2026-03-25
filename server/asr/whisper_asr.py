import io
import os
import struct
import time
import wave
import logging
import site
from pathlib import Path

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)

# Force huggingface_hub to always show tqdm progress bars even in subprocesses
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")


def _configure_windows_cuda_dll_paths() -> None:
    """Expose CUDA DLLs from pip-installed NVIDIA wheels on Windows."""
    if os.name != "nt":
        return

    candidate_roots = []
    try:
        candidate_roots.extend(Path(path) for path in site.getsitepackages())
    except Exception:
        pass

    user_site = site.getusersitepackages()
    if user_site:
        candidate_roots.append(Path(user_site))

    seen: set[str] = set()
    dll_dirs: list[Path] = []
    for root in candidate_roots:
        for relative in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
            dll_dir = root / relative
            dll_dir_str = str(dll_dir)
            if dll_dir.is_dir() and dll_dir_str not in seen:
                seen.add(dll_dir_str)
                dll_dirs.append(dll_dir)

    if not dll_dirs:
        return

    current_path = os.environ.get("PATH", "")
    missing_dirs = [str(path) for path in dll_dirs if str(path) not in current_path]
    if missing_dirs:
        os.environ["PATH"] = os.pathsep.join(missing_dirs + [current_path]) if current_path else os.pathsep.join(missing_dirs)

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for dll_dir in dll_dirs:
            try:
                add_dll_directory(str(dll_dir))
            except OSError:
                logger.warning("Failed to add CUDA DLL directory: %s", dll_dir)


_configure_windows_cuda_dll_paths()

from faster_whisper import WhisperModel


class WhisperASR:
    """Synchronous wrapper around faster-whisper.
    
    Designed to be called via asyncio.to_thread() from async code.
    The model is loaded once and reused across all requests.
    """

    def __init__(self):
        logger.info(
            "Loading Whisper model '%s' on %s (%s) …",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
            settings.WHISPER_COMPUTE_TYPE,
        )
        # Check cache so we can tell the user whether a download is needed
        cache_dir = os.path.expanduser(
            f"~/.cache/huggingface/hub/models--Systran--faster-whisper-{settings.WHISPER_MODEL}"
        )
        if not os.path.isdir(cache_dir):
            logger.info(
                "Model not in local cache — downloading from HuggingFace Hub "
                "(this may take a minute for the first run) …"
            )
        else:
            logger.info("Model found in cache: %s", cache_dir)

        t0 = time.perf_counter()
        self._model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
            cpu_threads=4,   # cap OpenMP threads; default (all cores) slows init
            num_workers=1,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Whisper model loaded in %.1f s.", elapsed)

    # ------------------------------------------------------------------
    def transcribe(self, raw_pcm: bytes) -> str:
        """Transcribe raw PCM bytes (int16, 16 kHz, mono) → text string."""
        audio_np = self._pcm_to_float32(raw_pcm)

        segments, info = self._model.transcribe(
            audio_np,
            beam_size=5,
            language=None,          # auto-detect; pin to "zh" for Chinese-only
            vad_filter=True,        # skip silent segments automatically
            vad_parameters={"min_silence_duration_ms": 500},
        )
        logger.info("Detected language: %s (%.0f%%)", info.language, info.language_probability * 100)

        text = " ".join(seg.text.strip() for seg in segments)
        return text.strip()

    # ------------------------------------------------------------------
    @staticmethod
    def _pcm_to_float32(raw_pcm: bytes) -> np.ndarray:
        """Convert 16-bit PCM bytes to float32 numpy array in [-1, 1]."""
        if len(raw_pcm) < 2:
            return np.zeros(1, dtype=np.float32)

        num_samples = len(raw_pcm) // 2
        samples = struct.unpack(f"<{num_samples}h", raw_pcm[: num_samples * 2])
        audio_np = np.array(samples, dtype=np.float32) / 32768.0
        return audio_np
