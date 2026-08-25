"""Atomic disk-image conversion using the installed Greaseweazle codecs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .create_image import CreateImageProgress, parse_create_progress
from .disk_formats import DiskFormat
from .operation import OperationController
from .subprocess_runner import run_streaming_process


@dataclass(frozen=True, slots=True)
class ConvertImageResult:
    succeeded: bool
    summary: str
    diagnostic: str = ""


def convert_image(
    source: Path,
    destination: Path,
    target_format: DiskFormat,
    *,
    progress: Callable[[CreateImageProgress], None] | None = None,
    controller: OperationController | None = None,
    timeout: float = 600,
    tracks: str | None = None,
) -> ConvertImageResult:
    executable = shutil.which("gw")
    if executable is None:
        return ConvertImageResult(
            False, "The Greaseweazle host tool (‘gw’) is unavailable."
        )
    if not target_format.gw_format:
        return ConvertImageResult(False, "Choose a concrete destination format.")
    if not source.is_file() or not destination.parent.is_dir():
        return ConvertImageResult(
            False, "The source or destination path is unavailable."
        )
    with tempfile.TemporaryDirectory(
        prefix=".greaseweazle-convert-", dir=destination.parent
    ) as temporary:
        output = Path(temporary) / f"converted{destination.suffix}"
        command = [executable, "convert"]
        if tracks is not None:
            command.extend(("--tracks", tracks))
        command.extend(
            (
                "--format",
                target_format.gw_format,
                str(source),
                str(output),
            )
        )

        def process_line(line: str) -> None:
            update = parse_create_progress(line, target_format)
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
            return ConvertImageResult(
                False, "Greaseweazle could not be started.", str(error)
            )
        diagnostic = process_result.output
        if process_result.cancelled:
            return ConvertImageResult(
                False, "Image conversion was cancelled safely.", diagnostic
            )
        if process_result.timed_out:
            return ConvertImageResult(False, "Image conversion timed out.", diagnostic)
        if process_result.return_code != 0 or not output.is_file():
            return ConvertImageResult(
                False, "The image could not be converted.", diagnostic
            )
        try:
            os.replace(output, destination)
        except OSError as error:
            return ConvertImageResult(
                False, "The converted image could not be saved.", str(error)
            )
    return ConvertImageResult(True, "Image converted successfully.", diagnostic)
