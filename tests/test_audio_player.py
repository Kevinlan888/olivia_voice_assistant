import sys
import types
import unittest
from unittest.mock import MagicMock, patch


sys.modules.setdefault(
    "pyaudio",
    types.SimpleNamespace(paInt16=8, paContinue=0, PyAudio=object),
)
sys.modules.setdefault(
    "miniaudio",
    types.SimpleNamespace(
        SampleFormat=types.SimpleNamespace(SIGNED16="SIGNED16"),
        decode=lambda *args, **kwargs: types.SimpleNamespace(samples=b"pcm"),
    ),
)

from client.audio_player import AudioPlayer


class TestAudioPlayer(unittest.TestCase):
    @patch("client.audio_player.manager")
    @patch("client.audio_player._decode_mp3", return_value=b"pcm")
    def test_play_uses_existing_pa_instance(self, _mock_decode, mock_manager):
        fake_stream = MagicMock()
        fake_pa = MagicMock()
        fake_pa.open.return_value = fake_stream
        mock_manager.get_pa.return_value = fake_pa

        player = AudioPlayer()
        player.play(b"mp3")

        mock_manager.get_pa.assert_called_once()
        mock_manager.fresh_pa.assert_not_called()


if __name__ == "__main__":
    unittest.main()
