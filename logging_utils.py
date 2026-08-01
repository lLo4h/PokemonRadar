from __future__ import annotations

import atexit
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO


class DailyLogStream:
    """Schreibt gleichzeitig ins CMD und in eine täglich wechselnde Logdatei."""

    def __init__(self, console: TextIO, logs_dir: Path, stream_name: str) -> None:
        self.console = console
        self.logs_dir = logs_dir
        self.stream_name = stream_name
        self._lock = threading.RLock()
        self._current_date = ""
        self._file: TextIO | None = None
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_file(self) -> TextIO:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._file is None or self._current_date != today:
            if self._file is not None:
                self._file.flush()
                self._file.close()

            self._current_date = today
            path = self.logs_dir / f"{today}.log"
            self._file = path.open("a", encoding="utf-8", buffering=1)

        return self._file

    @property
    def current_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.logs_dir / f"{today}.log"

    def write(self, text: str) -> int:
        if not text:
            return 0

        with self._lock:
            if not _DASHBOARD_MODE:
                self.console.write(text)
                self.console.flush()

            log_file = self._ensure_file()
            log_file.write(text)
            log_file.flush()

        return len(text)

    def flush(self) -> None:
        with self._lock:
            self.console.flush()
            if self._file is not None:
                self._file.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.console, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self.console, "encoding", None) or "utf-8"

    def close_log(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None


_INSTALLED = False
_STDOUT_STREAM: DailyLogStream | None = None
_STDERR_STREAM: DailyLogStream | None = None
_DASHBOARD_MODE = False


def setup_console_logging(logs_dir: str | Path = "logs") -> Path:
    """Aktiviert CMD-Ausgabe plus tägliche Logdatei.

    Mehrfaches Aufrufen ist sicher. Die Logdatei liegt standardmässig unter:
    logs/JJJJ-MM-TT.log
    """
    global _INSTALLED, _STDOUT_STREAM, _STDERR_STREAM

    if _INSTALLED and _STDOUT_STREAM is not None:
        return _STDOUT_STREAM.current_path.resolve()

    directory = Path(logs_dir)
    _STDOUT_STREAM = DailyLogStream(sys.stdout, directory, "stdout")
    _STDERR_STREAM = DailyLogStream(sys.stderr, directory, "stderr")

    sys.stdout = _STDOUT_STREAM
    sys.stderr = _STDERR_STREAM
    _INSTALLED = True

    def _close_logs() -> None:
        if _STDOUT_STREAM is not None:
            _STDOUT_STREAM.close_log()
        if _STDERR_STREAM is not None:
            _STDERR_STREAM.close_log()

    atexit.register(_close_logs)
    return _STDOUT_STREAM.current_path.resolve()


def set_dashboard_mode(enabled: bool) -> None:
    """Blendet normale print-Ausgaben im Terminal aus, protokolliert sie aber weiter."""
    global _DASHBOARD_MODE
    _DASHBOARD_MODE = bool(enabled)


def console_write(text: str, *, clear: bool = False) -> None:
    """Schreibt nur ins echte Terminal und nicht in die Logdatei."""
    stream = _STDOUT_STREAM
    console = stream.console if stream is not None else sys.__stdout__
    if clear:
        # ANSI: Cursor nach oben links und Bildschirm leeren.
        console.write("\033[2J\033[H")
    console.write(text)
    console.flush()
