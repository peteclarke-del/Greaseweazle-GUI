"""Non-destructive Greaseweazle drive diagnostics and cleaning."""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass

from .operation import OperationController


@dataclass(frozen=True, slots=True)
class HardwareToolResult:
    succeeded: bool
    summary: str
    output: str = ""


def run_hardware_tool(
    action: str,
    *,
    drive: str = "A",
    controller: OperationController | None = None,
    timeout: float = 180,
) -> HardwareToolResult:
    if action not in {"rpm", "bandwidth", "clean"}:
        return HardwareToolResult(False, "Unsupported hardware tool.")
    executable = shutil.which("gw")
    if executable is None:
        return HardwareToolResult(False, "The Greaseweazle host tool is unavailable.")
    command = [executable, action]
    if action in {"rpm", "clean"}:
        command.extend(("--drive", drive))
    if action == "rpm":
        command.extend(("--nr", "5"))
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as error:
        return HardwareToolResult(
            False, "Greaseweazle could not be started.", str(error)
        )
    if controller is not None:
        controller.register(process)
    timed_out = threading.Event()

    def stop() -> None:
        if process.poll() is None:
            timed_out.set()
            process.kill()

    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    try:
        output, _unused = process.communicate()
    finally:
        timer.cancel()
        if controller is not None:
            controller.unregister(process)
    output = output.strip()
    if controller is not None and controller.cancelled:
        return HardwareToolResult(False, "The operation was cancelled safely.", output)
    if timed_out.is_set():
        return HardwareToolResult(False, "The hardware operation timed out.", output)
    if process.returncode != 0:
        return HardwareToolResult(False, "The hardware operation failed.", output)
    summaries = {
        "rpm": "Drive speed measurement complete.",
        "bandwidth": "USB bandwidth test complete.",
        "clean": "Drive cleaning cycle complete.",
    }
    return HardwareToolResult(True, summaries[action], output)
