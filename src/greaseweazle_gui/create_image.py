"""Create media-level blank images using Greaseweazle disk definitions."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .disk_formats import DiskFormat
from .filesystem_formatters import (
    FilesystemFormatError,
    initialise_filesystem,
)
from .operation import OperationController
from .subprocess_runner import run_streaming_process

# ``ibm.scan`` detects unknown IBM layouts and has no geometry to create.
# Greaseweazle currently advertises ``zx.rocky.ss40`` but rejects its own
# definition (40 cylinders with a 0-79 cylinder track range).
NON_CREATABLE_FORMATS = frozenset({"ibm.scan", "zx.rocky.ss40"})


@dataclass(frozen=True, slots=True)
class CreateImageResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""
    filesystem: str | None = None


@dataclass(frozen=True, slots=True)
class CreateImageProgress:
    fraction: float
    cylinder: int
    head: int
    track_number: int
    track_count: int
    message: str


_TRACK = re.compile(r"^T(\d+)\.(\d+):\s*(.*)$")


def parse_create_progress(
    line: str, disk_format: DiskFormat
) -> CreateImageProgress | None:
    match = _TRACK.match(line.strip())
    if match is None:
        return None
    cylinder, head = int(match.group(1)), int(match.group(2))
    if cylinder >= disk_format.cylinders or head >= disk_format.heads:
        return None
    index = cylinder * disk_format.heads + head
    return CreateImageProgress(
        min((index + 1) / disk_format.track_count, 1.0),
        cylinder,
        head,
        index + 1,
        disk_format.track_count,
        match.group(3),
    )


def create_blank_image(
    destination: Path,
    disk_format: DiskFormat,
    timeout: float = 300,
    progress: Callable[[CreateImageProgress], None] | None = None,
    controller: OperationController | None = None,
    initialise: bool = False,
    volume_label: str = "BLANK",
) -> CreateImageResult:
    """Create an atomically replaced blank image for *disk_format*.

    Greaseweazle has no ``create`` action. Converting an empty generic IMG
    source makes each codec initialise every configured sector or bitcell and
    lets the destination suffix select the appropriate image container.
    """
    executable = shutil.which("gw")
    if executable is None:
        return CreateImageResult(
            False, "The Greaseweazle host tool (‘gw’) is unavailable."
        )
    if not disk_format.gw_format:
        return CreateImageResult(False, "Choose a specific Greaseweazle format.")
    if disk_format.gw_format in NON_CREATABLE_FORMATS:
        return CreateImageResult(
            False,
            "This Greaseweazle definition can detect disks but cannot create them.",
        )
    if not destination.parent.is_dir():
        return CreateImageResult(False, "The destination folder does not exist.")

    with tempfile.TemporaryDirectory(
        prefix=".greaseweazle-create-", dir=destination.parent
    ) as temporary:
        work_directory = Path(temporary)
        source = work_directory / "empty.img"
        output = work_directory / f"blank{destination.suffix}"
        media_output = (
            work_directory / f"blank-native{disk_format.suffix}"
            if initialise and destination.suffix.lower() == ".hfe"
            else output
        )
        source.touch()
        command = [
            executable,
            "convert",
            "--format",
            disk_format.gw_format,
            str(source),
            str(media_output),
        ]

        def process_line(line: str) -> None:
            update = parse_create_progress(line, disk_format)
            if update is not None and progress is not None:
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
            return CreateImageResult(
                False, f"Greaseweazle could not be started: {error}"
            )

        diagnostic = process_result.output
        if process_result.cancelled:
            return CreateImageResult(
                False, "Creating the image was cancelled.", diagnostic
            )
        if process_result.timed_out:
            return CreateImageResult(False, "Creating the image timed out.", diagnostic)
        if process_result.return_code != 0:
            return CreateImageResult(
                False,
                "Greaseweazle could not create this image format.",
                diagnostic,
            )
        if not media_output.is_file() or media_output.stat().st_size == 0:
            return CreateImageResult(
                False,
                "Greaseweazle finished without creating a usable image.",
                diagnostic,
            )
        filesystem: str | None = None
        if initialise:
            try:
                filesystem = initialise_filesystem(
                    media_output, disk_format, volume_label
                )
            except (OSError, FilesystemFormatError) as error:
                return CreateImageResult(
                    False,
                    "The media image was created, but its filesystem could not be initialised.",
                    str(error),
                )
        if media_output != output:
            try:
                hfe_result = run_streaming_process(
                    [
                        executable,
                        "convert",
                        "--format",
                        disk_format.gw_format,
                        str(media_output),
                        str(output),
                    ],
                    timeout=timeout,
                    on_line=process_line,
                    controller=controller,
                    process_factory=subprocess.Popen,
                )
            except OSError as error:
                return CreateImageResult(
                    False, "The HFE container could not be created.", str(error)
                )
            diagnostic = f"{diagnostic}\n{hfe_result.output}".strip()
            if (
                hfe_result.cancelled
                or hfe_result.timed_out
                or hfe_result.return_code != 0
                or not output.is_file()
                or output.stat().st_size == 0
            ):
                return CreateImageResult(
                    False, "The HFE container could not be created.", diagnostic
                )
        try:
            os.replace(output, destination)
        except OSError as error:
            return CreateImageResult(False, "The image could not be saved.", str(error))

    return CreateImageResult(
        True,
        (
            f"Blank image created with {filesystem}."
            if filesystem
            else "Blank media image created. Initialise it on the target system before storing files."
        ),
        filesystem=filesystem,
    )
