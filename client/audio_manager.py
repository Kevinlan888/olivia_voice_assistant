"""Global audio device coordinator.

ALSA on single-card Linux systems (e.g. Raspberry Pi) allows only one
capture stream and one playback stream at a time.  Without coordination,
opening a second stream raises OSError -9985 "Device unavailable", and
reusing a stale PyAudio instance after PortAudio re-enumerates devices
raises OSError -9997 "Invalid sample rate".

This module provides a process-wide singleton (``manager``) that owns
the single PyAudio instance.  ``fresh_pa()`` always terminates the old
instance and returns a new one, making stale-state errors impossible.

Usage pattern
-------------
  Any stream (input or output):
    pa = manager.fresh_pa()
    stream = pa.open(...)
    ...
    stream.stop_stream(); stream.close()

  Process shutdown:
    manager.terminate_pa()
"""

import logging
import os
import threading
import pyaudio

logger = logging.getLogger(__name__)


class AudioManager:
    """Process-wide audio coordinator. Use the module-level ``manager`` singleton."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pa: pyaudio.PyAudio | None = None

    # ── Advisory lock ────────────────────────────────────────────────────────
    @property
    def lock(self) -> threading.Lock:
        """Optional lock callers can hold during device transitions."""
        return self._lock

    # ── PyAudio lifecycle ─────────────────────────────────────────────────────
    def get_pa(self) -> pyaudio.PyAudio:
        """Return the current PyAudio instance, creating one if needed.

        Unlike fresh_pa(), this does NOT terminate and recreate the instance.
        Use this when the existing PortAudio context is still valid (e.g. the
        previous stream was the same direction — input → input).
        """
        if self._pa is None:
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            saved_fd2 = os.dup(2)
            try:
                os.dup2(devnull_fd, 2)
                self._pa = pyaudio.PyAudio()
            finally:
                os.dup2(saved_fd2, 2)
                os.close(saved_fd2)
                os.close(devnull_fd)
            logger.debug("PyAudio initialised")
        return self._pa

    def fresh_pa(self) -> pyaudio.PyAudio:
        """Terminate the existing PyAudio instance and return a brand-new one.

        Must be called before opening any new stream to guarantee a clean
        PortAudio context.  PortAudio writes ALSA/JACK probe noise directly
        to C-level stderr on every init; we suppress it by briefly redirecting
        file descriptor 2 to /dev/null.
        """
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass

        # Suppress PortAudio's C-level ALSA/JACK/PulseAudio probe messages.
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_fd2 = os.dup(2)
        try:
            os.dup2(devnull_fd, 2)
            self._pa = pyaudio.PyAudio()
        finally:
            os.dup2(saved_fd2, 2)
            os.close(saved_fd2)
            os.close(devnull_fd)

        logger.debug("PyAudio re-initialised")
        return self._pa

    def terminate_pa(self) -> None:
        """Terminate the managed PyAudio instance (call at process shutdown)."""
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
            logger.debug("PyAudio terminated")


# Module-level singleton — import and use this everywhere.
manager = AudioManager()
