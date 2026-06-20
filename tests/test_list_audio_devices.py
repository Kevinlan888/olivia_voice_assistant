import io
import sys
import types
import unittest
from contextlib import redirect_stdout


def _install_pyaudio_stub() -> None:
    sys.modules["pyaudio"] = types.SimpleNamespace(PyAudio=object)


class TestListAudioDevices(unittest.TestCase):
    def test_main_prints_devices_and_default_sections(self):
        _install_pyaudio_stub()
        import list_audio_devices

        fake_pa = object()
        list_audio_devices.create_pa = lambda: fake_pa
        list_audio_devices.terminate_pa = lambda pa: None
        list_audio_devices.collect_report = lambda pa: {
            "device_count": 1,
            "devices": [
                {
                    "index": 2,
                    "name": "USB Mic",
                    "max_input_channels": 1,
                    "max_output_channels": 0,
                    "default_sample_rate": 16000.0,
                }
            ],
            "default_input": {
                "index": 2,
                "name": "USB Mic",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_sample_rate": 16000.0,
            },
            "default_output_error": "No default output device",
        }

        output = io.StringIO()
        with redirect_stdout(output):
            list_audio_devices.main()

        text = output.getvalue()
        self.assertIn("Device count: 1", text)
        self.assertIn("Index: 2", text)
        self.assertIn("Name: USB Mic", text)
        self.assertIn("Default input device:", text)
        self.assertIn("Default output device: No default output device", text)


if __name__ == "__main__":
    unittest.main()
