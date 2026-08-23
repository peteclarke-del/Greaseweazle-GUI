"""Thread-safe cancellation for Greaseweazle subprocess operations."""

from __future__ import annotations

import signal
import subprocess
import threading


class OperationController:
    """Request graceful cancellation by delivering the terminal interrupt."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def register(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = process
            cancelled = self._cancelled.is_set()
        if cancelled:
            self._interrupt(process)

    def unregister(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._process is process:
                self._process = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None:
            self._interrupt(process)

    @staticmethod
    def _interrupt(process: subprocess.Popen[str]) -> None:
        try:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        except OSError:
            # The process exited between poll() and signal delivery.
            pass
