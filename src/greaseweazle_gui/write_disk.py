"""Write a disk image with live Greaseweazle progress."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from collections.abc import Callable

from .disk_formats import DiskFormat
from .operation import OperationController


@dataclass(frozen=True, slots=True)
class WriteResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""
    verified: bool = False
    progress: tuple[WriteProgress, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteProgress:
    fraction: float
    cylinder: int
    head: int
    track_number: int
    track_count: int
    retry: str | None
    message: str


_TRACK = re.compile(r"^T(\d+)\.(\d+)(?:\s+->.*?)?:\s*(.*)$")
_RETRY = re.compile(r"Retry #(\d+)")


def parse_write_progress(line: str, disk_format: DiskFormat) -> WriteProgress | None:
    match = _TRACK.match(line.strip())
    if match is None:
        return None
    cylinder, head = int(match.group(1)), int(match.group(2))
    if cylinder >= disk_format.cylinders or head >= disk_format.heads:
        return None
    message = match.group(3)
    index = cylinder * disk_format.heads + head
    retry = _RETRY.search(message)
    return WriteProgress(
        min((index + 1) / disk_format.track_count, 1.0),
        cylinder,
        head,
        index + 1,
        disk_format.track_count,
        retry.group(1) if retry else None,
        message,
    )


def write_disk(
    image_path: Path,
    disk_format: DiskFormat,
    timeout: float = 900,
    progress: Callable[[WriteProgress], None] | None = None,
    controller: OperationController | None = None,
    drive: str | None = None,
) -> WriteResult:
    executable = shutil.which("gw")
    if executable is None:
        return WriteResult(False, "The Greaseweazle host tool (‘gw’) is unavailable.")
    command = [executable, "write"]
    if drive is not None:
        command.extend(("--drive", drive))
    if disk_format.gw_format:
        command.extend(("--format", disk_format.gw_format))
    command.append(str(image_path))
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environment,
        )
    except OSError as error:
        return WriteResult(False, f"Greaseweazle could not be started: {error}")
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
    lines: list[str] = []
    progress_updates: list[WriteProgress] = []
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                lines.append(line)
                update = parse_write_progress(line, disk_format)
                if update is not None:
                    progress_updates.append(update)
                    if progress is not None:
                        progress(update)
        return_code = process.wait()
    finally:
        timer.cancel()
        if controller is not None:
            controller.unregister(process)
    output = "\n".join(lines).strip()
    if controller is not None and controller.cancelled:
        return WriteResult(
            False,
            "Writing was cancelled safely.",
            output,
            progress=tuple(progress_updates),
        )
    if timed_out.is_set():
        return WriteResult(
            False,
            "Writing the disk timed out.",
            output,
            progress=tuple(progress_updates),
        )
    if return_code != 0:
        return WriteResult(
            False,
            "The disk could not be written or verified.",
            output,
            progress=tuple(progress_updates),
        )
    verified = "All tracks verified" in output
    summary = (
        "The disk was written and verified."
        if verified
        else "The disk was written. Greaseweazle reported that track verification was unavailable."
    )
    return WriteResult(True, summary, output, verified, tuple(progress_updates))
