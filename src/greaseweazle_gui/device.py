"""Detection and description of an attached Greaseweazle device."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import shutil
import subprocess
from typing import Mapping


_FIELD_PATTERN = re.compile(r"^\s{2,}([^:]+):\s*(.*?)\s*$")


@dataclass(frozen=True, slots=True)
class DeviceProbeResult:
    """Result of invoking ``gw info``."""

    connected: bool
    summary: str
    details: Mapping[str, str] = field(default_factory=dict)
    diagnostic: str = ""

    @property
    def model(self) -> str:
        return self.details.get("Model", "Greaseweazle")

    @property
    def port(self) -> str:
        return self.details.get("Port", "Connected")


def parse_info_output(output: str) -> DeviceProbeResult:
    """Parse the human-readable output emitted by ``gw info``.

    Greaseweazle host tools return status 0 even when the device block says
    ``Not found``, so detection must inspect the device section itself.
    """
    lines = output.splitlines()
    try:
        device_start = next(
            index for index, line in enumerate(lines) if line.strip() == "Device:"
        )
    except StopIteration:
        return DeviceProbeResult(
            False,
            "The Greaseweazle response did not contain device information.",
            diagnostic=output.strip(),
        )

    device_lines: list[str] = []
    for line in lines[device_start + 1 :]:
        if line and not line[0].isspace():
            break
        if line.strip():
            device_lines.append(line)

    if not device_lines or any(line.strip().lower() == "not found" for line in device_lines):
        return DeviceProbeResult(
            False,
            "No connected Greaseweazle was found.",
            diagnostic=output.strip(),
        )

    details: dict[str, str] = {}
    for line in device_lines:
        match = _FIELD_PATTERN.match(line)
        if match:
            details[match.group(1).strip()] = match.group(2).strip()

    if not details:
        return DeviceProbeResult(
            False,
            "The Greaseweazle device information could not be understood.",
            diagnostic=output.strip(),
        )

    return DeviceProbeResult(
        True,
        "Greaseweazle connected and ready.",
        details=details,
        diagnostic=output.strip(),
    )


def detect_device(timeout: float = 8.0) -> DeviceProbeResult:
    """Locate the host tool and query it for an attached device."""
    if os.environ.get("GREASEWEAZLE_GUI_DEMO") == "1":
        return DeviceProbeResult(
            True,
            "Simulated Greaseweazle connected.",
            details={"Model": "Greaseweazle (demo)", "Port": "Simulation"},
        )

    executable = shutil.which("gw")
    if executable is None:
        return DeviceProbeResult(
            False,
            "The Greaseweazle host tool (‘gw’) is not installed or is not on PATH.",
        )

    try:
        completed = subprocess.run(
            [executable, "info"],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return DeviceProbeResult(
            False,
            "The Greaseweazle did not respond in time.",
        )
    except OSError as error:
        return DeviceProbeResult(
            False,
            f"The Greaseweazle host tool could not be started: {error}",
        )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        return DeviceProbeResult(
            False,
            "The Greaseweazle host tool could not communicate with the device.",
            diagnostic=output.strip(),
        )

    return parse_info_output(output)

