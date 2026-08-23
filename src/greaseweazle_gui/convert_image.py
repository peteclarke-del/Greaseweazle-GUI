"""Atomic disk-image conversion using the installed Greaseweazle codecs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from .create_image import CreateImageProgress, parse_create_progress
from .disk_formats import DiskFormat
from .operation import OperationController


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
) -> ConvertImageResult:
    executable = shutil.which("gw")
    if executable is None:
        return ConvertImageResult(False, "The Greaseweazle host tool (‘gw’) is unavailable.")
    if not target_format.gw_format:
        return ConvertImageResult(False, "Choose a concrete destination format.")
    if not source.is_file() or not destination.parent.is_dir():
        return ConvertImageResult(False, "The source or destination path is unavailable.")
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    with tempfile.TemporaryDirectory(
        prefix=".greaseweazle-convert-", dir=destination.parent
    ) as temporary:
        output = Path(temporary) / f"converted{destination.suffix}"
        command = [
            executable,
            "convert",
            "--format",
            target_format.gw_format,
            str(source),
            str(output),
        ]
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
            return ConvertImageResult(False, "Greaseweazle could not be started.", str(error))
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
        try:
            if process.stdout is not None:
                for raw_line in process.stdout:
                    line = raw_line.rstrip("\r\n")
                    lines.append(line)
                    update = parse_create_progress(line, target_format)
                    if update is not None and progress is not None:
                        progress(update)
            return_code = process.wait()
        finally:
            timer.cancel()
            if controller is not None:
                controller.unregister(process)
        diagnostic = "\n".join(lines).strip()
        if controller is not None and controller.cancelled:
            return ConvertImageResult(False, "Image conversion was cancelled safely.", diagnostic)
        if timed_out.is_set():
            return ConvertImageResult(False, "Image conversion timed out.", diagnostic)
        if return_code != 0 or not output.is_file():
            return ConvertImageResult(False, "The image could not be converted.", diagnostic)
        try:
            os.replace(output, destination)
        except OSError as error:
            return ConvertImageResult(False, "The converted image could not be saved.", str(error))
    return ConvertImageResult(True, "Image converted successfully.")
