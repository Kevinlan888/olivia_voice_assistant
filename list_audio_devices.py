"""List available PyAudio devices and default input/output devices."""

from __future__ import annotations

from typing import Any

import pyaudio


def create_pa() -> pyaudio.PyAudio:
    return pyaudio.PyAudio()


def terminate_pa(pa: pyaudio.PyAudio) -> None:
    pa.terminate()


def _device_summary(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": info["index"],
        "name": info["name"],
        "max_input_channels": info["maxInputChannels"],
        "max_output_channels": info["maxOutputChannels"],
        "default_sample_rate": info["defaultSampleRate"],
    }


def collect_report(pa: pyaudio.PyAudio) -> dict[str, Any]:
    report: dict[str, Any] = {
        "device_count": pa.get_device_count(),
        "devices": [],
    }

    for index in range(report["device_count"]):
        info = pa.get_device_info_by_index(index)
        report["devices"].append(_device_summary(info))

    try:
        report["default_input"] = _device_summary(pa.get_default_input_device_info())
    except Exception as exc:
        report["default_input_error"] = str(exc)

    try:
        report["default_output"] = _device_summary(pa.get_default_output_device_info())
    except Exception as exc:
        report["default_output_error"] = str(exc)

    return report


def _print_device(label: str, device: dict[str, Any]) -> None:
    print(label)
    print(f"  Index: {device['index']}")
    print(f"  Name: {device['name']}")
    print(f"  Max input channels: {device['max_input_channels']}")
    print(f"  Max output channels: {device['max_output_channels']}")
    print(f"  Default sample rate: {device['default_sample_rate']}")


def print_report(report: dict[str, Any]) -> None:
    print(f"Device count: {report['device_count']}")
    print()

    for device in report["devices"]:
        _print_device("Device:", device)
        print()

    if "default_input" in report:
        _print_device("Default input device:", report["default_input"])
    else:
        print(f"Default input device: {report['default_input_error']}")
    print()

    if "default_output" in report:
        _print_device("Default output device:", report["default_output"])
    else:
        print(f"Default output device: {report['default_output_error']}")


def main() -> None:
    pa = create_pa()
    try:
        report = collect_report(pa)
        print_report(report)
    finally:
        terminate_pa(pa)


if __name__ == "__main__":
    main()
