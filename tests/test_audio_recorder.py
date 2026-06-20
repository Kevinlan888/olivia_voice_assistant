"""Unit tests for chunk-driven AudioRecorder.

Uses a fake Silero VAD to avoid real model dependency.
"""

import struct
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("client.silero_vad", types.SimpleNamespace(SileroVAD=object))
import client.audio_recorder  # Ensure patch() can resolve client.audio_recorder.*


def _silence_chunk(frame_length: int = 512) -> bytes:
    return b"\x00" * (frame_length * 2)


def _speech_chunk(frame_length: int = 512) -> bytes:
    """Simulated speech: non-zero samples that VAD would classify as speech."""
    return struct.pack(f"{frame_length}h", *([16000] * frame_length))


class _FakeVAD:
    """Mimics SileroVAD with controllable speech probability."""

    def __init__(self, probabilities: list[float] | None = None):
        """If probabilities is given, each call returns the next value.
        Otherwise, returns 0.0 for silence chunks and 0.9 for speech chunks."""
        self._probs = list(probabilities or [])
        self._idx = 0
        self.reset_count = 0

    def reset(self):
        self._idx = 0
        self.reset_count += 1

    def __call__(self, chunk_bytes: bytes) -> float:
        if self._probs:
            if self._idx < len(self._probs):
                val = self._probs[self._idx]
            else:
                val = self._probs[-1]
            self._idx += 1
            return val
        # Auto-detect: non-zero samples = speech
        samples = struct.unpack(f"{len(chunk_bytes) // 2}h", chunk_bytes)
        if any(s != 0 for s in samples[:10]):
            return 0.9
        return 0.05


class TestAudioRecorderStartUtterance(unittest.TestCase):
    """Test start_utterance() with prebuffer."""

    @patch("client.audio_recorder.SileroVAD", return_value=_FakeVAD())
    @patch("client.audio_recorder.settings")
    def test_prebuffer_injected(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()

        prebuffer = [_silence_chunk() for _ in range(5)]
        recorder.start_utterance(prebuffer)

        # Internal state should reflect prebuffer
        self.assertEqual(recorder._total_chunks, 5)
        self.assertEqual(len(recorder._frames), 5)
        self.assertFalse(recorder.is_speech_started)

    @patch("client.audio_recorder.SileroVAD", return_value=_FakeVAD())
    @patch("client.audio_recorder.settings")
    def test_vad_reset_on_start(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()

        # Start utterance twice — VAD should be reset each time
        recorder.start_utterance([])
        recorder.start_utterance([])

        fake_vad = mock_vad_cls.return_value
        self.assertEqual(fake_vad.reset_count, 2)

    @patch("client.audio_recorder.SileroVAD", return_value=_FakeVAD())
    @patch("client.audio_recorder.settings")
    def test_prebuffer_forwarded_to_callback_on_start(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        callback = MagicMock()

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder(on_speech_chunk=callback)

        prebuffer = [_speech_chunk(), _speech_chunk()]
        recorder.start_utterance(prebuffer)

        self.assertEqual(callback.call_count, 2)


class TestAudioRecorderAppendChunk(unittest.TestCase):
    """Test append_chunk() VAD logic."""

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_silence_does_not_complete(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        # All silence probabilities
        fake_vad = _FakeVAD([0.05] * 100)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        for _ in range(50):
            done = recorder.append_chunk(_silence_chunk())
            self.assertFalse(done)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_speech_then_silence_completes(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 0.1  # short to trigger quickly
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        # 5 speech chunks, then sustained silence
        probs = [0.9] * 5 + [0.05] * 50
        fake_vad = _FakeVAD(probs)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        done = False
        for _ in range(55):
            done = recorder.append_chunk(_speech_chunk())
            if done:
                break

        self.assertTrue(done)
        self.assertTrue(recorder.is_speech_started)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_max_duration_completes(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 0.1
        mock_settings.MAX_RECORDING_SECONDS = 0.5  # very short max

        # Continuous speech — no silence
        fake_vad = _FakeVAD([0.9] * 100)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        done = False
        for _ in range(100):
            done = recorder.append_chunk(_speech_chunk())
            if done:
                break

        self.assertTrue(done)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_on_speech_chunk_callback(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 0.1
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        # First 2 chunks: silence, then speech
        probs = [0.05, 0.05, 0.9, 0.9, 0.9, 0.05] * 10
        fake_vad = _FakeVAD(probs)
        mock_vad_cls.return_value = fake_vad

        callback = MagicMock()
        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder(on_speech_chunk=callback)
        recorder.start_utterance([])

        # Feed 2 silence + 1 speech
        recorder.append_chunk(_silence_chunk())  # silence
        recorder.append_chunk(_silence_chunk())  # silence
        recorder.append_chunk(_speech_chunk())   # speech starts

        # Upload stays continuous even before VAD confirms speech.
        self.assertEqual(callback.call_count, 3)

        # More speech chunks
        recorder.append_chunk(_speech_chunk())
        recorder.append_chunk(_speech_chunk())
        self.assertEqual(callback.call_count, 5)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_callback_runs_for_live_chunks_before_vad_confirms_speech(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 0.1
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        fake_vad = _FakeVAD([0.05, 0.05, 0.9])
        mock_vad_cls.return_value = fake_vad

        callback = MagicMock()
        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder(on_speech_chunk=callback)
        recorder.start_utterance([])

        recorder.append_chunk(_speech_chunk())
        recorder.append_chunk(_speech_chunk())
        recorder.append_chunk(_speech_chunk())

        self.assertEqual(callback.call_count, 3)


class TestAudioRecorderFinishUtterance(unittest.TestCase):
    """Test finish_utterance() output."""

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_no_speech_returns_none(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        fake_vad = _FakeVAD([0.05] * 100)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        # Feed chunks but never trigger speech
        for _ in range(10):
            recorder.append_chunk(_silence_chunk())

        result = recorder.finish_utterance()
        self.assertIsNone(result)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_prebuffer_included_in_output(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 0.1
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        # Prebuffer silence, then speech, then silence to complete
        probs = [0.05] * 5 + [0.9] * 5 + [0.05] * 50
        fake_vad = _FakeVAD(probs)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()

        prebuffer = [_silence_chunk() for _ in range(5)]
        recorder.start_utterance(prebuffer)

        # Feed live chunks until done
        chunk_bytes = 512 * 2
        for _ in range(60):
            done = recorder.append_chunk(_speech_chunk())
            if done:
                break

        pcm = recorder.finish_utterance()
        self.assertIsNotNone(pcm)
        # PCM should include the 5 prebuffer chunks
        self.assertGreaterEqual(len(pcm), 5 * chunk_bytes)


class TestAudioRecorderIsSpeechStarted(unittest.TestCase):
    """Test is_speech_started property."""

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_false_before_speech(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        fake_vad = _FakeVAD([0.05] * 100)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        recorder.append_chunk(_silence_chunk())
        self.assertFalse(recorder.is_speech_started)

    @patch("client.audio_recorder.SileroVAD")
    @patch("client.audio_recorder.settings")
    def test_true_after_speech(self, mock_settings, mock_vad_cls):
        mock_settings.SAMPLE_RATE = 16000
        mock_settings.CHUNK_FRAMES = 512
        mock_settings.SILERO_SPEECH_THRESHOLD = 0.5
        mock_settings.SILENCE_SECONDS = 0.8
        mock_settings.MIN_RECORDING_SECONDS = 1.0
        mock_settings.MAX_RECORDING_SECONDS = 15.0

        fake_vad = _FakeVAD([0.05, 0.9] + [0.05] * 100)
        mock_vad_cls.return_value = fake_vad

        from client.audio_recorder import AudioRecorder
        recorder = AudioRecorder()
        recorder.start_utterance([])

        recorder.append_chunk(_silence_chunk())  # silence
        self.assertFalse(recorder.is_speech_started)

        recorder.append_chunk(_speech_chunk())  # speech
        self.assertTrue(recorder.is_speech_started)

        # Remains true even after silence
        recorder.append_chunk(_silence_chunk())
        self.assertTrue(recorder.is_speech_started)


if __name__ == "__main__":
    unittest.main()
