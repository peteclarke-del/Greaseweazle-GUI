"""Write a disk image with live Greaseweazle progress."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import DiskFormat
from .operation import OperationController
from .subprocess_runner import run_streaming_process


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
    if disk_format.gw_format and not disk_format.direct_write:
        command.extend(("--format", disk_format.gw_format))
    command.append(str(image_path))
    progress_updates: list[WriteProgress] = []

    def process_line(line: str) -> None:
        update = parse_write_progress(line, disk_format)
        if update is not None:
            progress_updates.append(update)
            if progress is not None:
                progress(update)

    try:
        process_result = run_streaming_process(
            command,
            timeout=timeout,
            on_line=process_line,
            controller=controller,
            process_factory=subprocess.Popen,
        )
    except OSError as error:
        return WriteResult(False, f"Greaseweazle could not be started: {error}")
    output = process_result.output
    if process_result.cancelled:
        return WriteResult(
            False,
            "Writing was cancelled safely.",
            output,
            progress=tuple(progress_updates),
        )
    if process_result.timed_out:
        return WriteResult(
            False,
            "Writing the disk timed out.",
            output,
            progress=tuple(progress_updates),
        )
    if process_result.return_code != 0:
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
