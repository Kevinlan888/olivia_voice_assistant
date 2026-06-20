# Audio Device Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Python script that prints all available PyAudio devices plus default input/output device details for local debugging.

**Architecture:** Keep the feature as a root-level utility script so it stays decoupled from client startup. Put the report-building logic into small pure functions inside the script so tests can stub `pyaudio` and verify formatting without real audio hardware.

**Tech Stack:** Python 3, `pyaudio`, `unittest`

---

### Task 1: Add a failing formatting/report test

**Files:**
- Create: `tests/test_list_audio_devices.py`
- Test: `tests/test_list_audio_devices.py`

- [ ] **Step 1: Write the failing test**

```python
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
            "default_input": {"index": 2, "name": "USB Mic"},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_list_audio_devices -v`
Expected: FAIL with `ModuleNotFoundError` for `list_audio_devices`

- [ ] **Step 3: Write minimal implementation**

```python
def main() -> None:
    pa = create_pa()
    try:
        report = collect_report(pa)
        print_report(report)
    finally:
        terminate_pa(pa)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_list_audio_devices -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-06-20-audio-device-listing.md tests/test_list_audio_devices.py list_audio_devices.py
git commit -m "feat: add audio device listing utility"
```

