"""Capture a disk image with the Greaseweazle command-line tools."""

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
class ReadResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""
    progress: tuple[ReadProgress, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadProgress:
    fraction: float
    cylinder: int
    head: int
    track_number: int
    track_count: int
    sectors_read: int | None
    sectors_total: int | None
    retry: str | None
    message: str


_TRACK_PATTERN = re.compile(r"^T(\d+)\.(\d+)(?:\s+<-.*?)?:\s*(.*)$")
_SECTOR_PATTERN = re.compile(r"\((\d+)/(\d+) sectors\)")
_RETRY_PATTERN = re.compile(r"\(Retry #([^)]+)\)")


def parse_progress_line(line: str, disk_format: DiskFormat) -> ReadProgress | None:
    """Turn a Greaseweazle track report into deterministic UI progress."""
    match = _TRACK_PATTERN.match(line.strip())
    if match is None:
        return None
    cylinder, head = int(match.group(1)), int(match.group(2))
    if cylinder >= disk_format.cylinders or head >= disk_format.heads:
        return None
    message = match.group(3)
    track_index = cylinder * disk_format.heads + head
    sector_match = _SECTOR_PATTERN.search(message)
    sectors_read: int | None = None
    sectors_total: int | None = None
    if sector_match is not None:
        sectors_read = int(sector_match.group(1))
        sectors_total = int(sector_match.group(2))
        within_track = min(sectors_read / sectors_total, 1.0) if sectors_total else 0.0
    elif "Giving up:" in message:
        within_track = 1.0
    else:
        # Raw/flux formats have no sector count, but the line is printed after
        # the track has been captured.
        within_track = 1.0
    retry_match = _RETRY_PATTERN.search(message)
    return ReadProgress(
        fraction=min((track_index + within_track) / disk_format.track_count, 1.0),
        cylinder=cylinder,
        head=head,
        track_number=track_index + 1,
        track_count=disk_format.track_count,
        sectors_read=sectors_read,
        sectors_total=sectors_total,
        retry=retry_match.group(1) if retry_match else None,
        message=message,
    )


def read_disk(
    disk_format: DiskFormat,
    destination: Path,
    timeout: float = 900,
    progress: Callable[[ReadProgress], None] | None = None,
    tracks: str | None = None,
    controller: OperationController | None = None,
    revolutions: int | None = None,
    retries: int | None = None,
    seek_retries: int | None = None,
    drive: str | None = None,
) -> ReadResult:
    """Read a physical disk into *destination* using ``gw read``."""
    executable = shutil.which("gw")
    if executable is None:
        return ReadResult(False, "The Greaseweazle host tool (‘gw’) is not available.")

    command = [executable, "read"]
    if drive is not None:
        command.extend(["--drive", drive])
    if disk_format.gw_format:
        command.extend(["--format", disk_format.gw_format])
    if revolutions is not None:
        command.extend(["--revs", str(revolutions)])
    if retries is not None:
        command.extend(["--retries", str(retries)])
    if seek_retries is not None:
        command.extend(["--seek-retries", str(seek_retries)])
    if tracks is not None:
        command.extend(["--tracks", tracks])
    elif not disk_format.gw_format:
        command.extend(["--tracks", "c=0-79:h=0-1"])
    command.append(str(destination))
    progress_updates: list[ReadProgress] = []

    def process_line(line: str) -> None:
        update = parse_progress_line(line, disk_format)
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
        return ReadResult(False, f"The Greaseweazle tool could not be started: {error}")
    output = process_result.output
    if process_result.cancelled:
        return ReadResult(
            False, "Reading was cancelled safely.", output, tuple(progress_updates)
        )
    if process_result.timed_out:
        return ReadResult(
            False, "Reading the disk timed out.", output, tuple(progress_updates)
        )
    if process_result.return_code != 0:
        return ReadResult(
            False, "The disk could not be read.", output, tuple(progress_updates)
        )
    if not destination.is_file():
        return ReadResult(
            False,
            "Greaseweazle finished without creating an image.",
            output,
            tuple(progress_updates),
        )
    return ReadResult(True, "Disk read successfully.", output, tuple(progress_updates))
