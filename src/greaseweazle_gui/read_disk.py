"""Capture a disk image with the Greaseweazle command-line tools."""

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


@dataclass(frozen=True, slots=True)
class ReadResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""


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
) -> ReadResult:
    """Read a physical disk into *destination* using ``gw read``."""
    executable = shutil.which("gw")
    if executable is None:
        return ReadResult(False, "The Greaseweazle host tool (‘gw’) is not available.")

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    try:
        command = [executable, "read"]
        if disk_format.gw_format:
            command.extend(["--format", disk_format.gw_format])
        if tracks is not None:
            command.extend(["--tracks", tracks])
        elif not disk_format.gw_format:
            command.extend(["--tracks", "c=0-79:h=0-1"])
        command.append(str(destination))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environment,
        )
    except OSError as error:
        return ReadResult(False, f"The Greaseweazle tool could not be started: {error}")

    timed_out = threading.Event()

    def stop_process() -> None:
        if process.poll() is None:
            timed_out.set()
            process.kill()

    timer = threading.Timer(timeout, stop_process)
    timer.daemon = True
    timer.start()
    output_lines: list[str] = []
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                output_lines.append(line)
                update = parse_progress_line(line, disk_format)
                if update is not None and progress is not None:
                    progress(update)
        return_code = process.wait()
    finally:
        timer.cancel()

    output = "\n".join(output_lines).strip()
    if timed_out.is_set():
        return ReadResult(False, "Reading the disk timed out.", output)
    if return_code != 0:
        return ReadResult(False, "The disk could not be read.", output)
    if not destination.is_file():
        return ReadResult(False, "Greaseweazle finished without creating an image.", output)
    return ReadResult(True, "Disk read successfully.", output)
