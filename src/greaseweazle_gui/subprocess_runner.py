"""Shared lifecycle management for streaming Greaseweazle commands."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .operation import OperationController


@dataclass(frozen=True, slots=True)
class StreamingProcessResult:
    return_code: int
    output: str
    timed_out: bool
    cancelled: bool


def run_streaming_process(
    command: Sequence[str],
    *,
    timeout: float,
    on_line: Callable[[str], None] | None = None,
    controller: OperationController | None = None,
    process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> StreamingProcessResult:
    """Run a line-buffered command with consistent timeout and cancellation."""
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    process = process_factory(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=environment,
    )
    if controller is not None:
        controller.register(process)

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
                if on_line is not None:
                    on_line(line)
        return_code = process.wait()
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        if controller is not None:
            controller.unregister(process)

    return StreamingProcessResult(
        return_code,
        "\n".join(output_lines).strip(),
        timed_out.is_set(),
        controller.cancelled if controller is not None else False,
    )
