"""Runs mkvpropedit for each file (JSON option file, parallel; cancelling skips the files not started yet)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from .command import FilePlan
from .mkvtoolnix import CREATE_NO_WINDOW


class RunStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    STOPPED = "stopped"

    @property
    def label(self) -> str:
        return {
            "ok": "Done",
            "warning": "With warnings",
            "error": "Error",
            "skipped": "Skipped",
            "cancelled": "Cancelled",
            "stopped": "Stopped",
        }[self.value]


@dataclass
class RunResult:
    path: str
    status: RunStatus
    exit_code: int | None
    output: str


def status_from_exit(code: int) -> RunStatus:
    return {0: RunStatus.OK, 1: RunStatus.WARNING}.get(code, RunStatus.ERROR)


class BatchRunner:
    def __init__(
        self,
        mkvpropedit: Path | str,
        plans: list[FilePlan],
        workers: int = 1,
        on_start: Callable[[FilePlan], None] | None = None,
        on_output: Callable[[str, str], None] | None = None,
        on_result: Callable[[RunResult], None] | None = None,
    ):
        self.exe = str(mkvpropedit)
        self.plans = plans
        self.workers = max(1, workers)
        self.on_start = on_start
        self.on_output = on_output
        self.on_result = on_result
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._running: dict[str, tuple[subprocess.Popen, float]] = {}  # path -> (process, start time)
        self._stopped: set[str] = set()

    def cancel(self) -> None:
        """Skips every file that has not been started yet.

        A running mkvpropedit is left alone on purpose: it writes into the file in place, and killing it
        half-way could leave a damaged file behind. It only takes a few seconds anyway.
        """
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def running(self) -> dict[str, float]:
        """Files that are being processed right now -> seconds since mkvpropedit was started."""
        now = time.monotonic()
        with self._lock:
            return {path: now - started for path, (_, started) in self._running.items()}

    def stop_file(self, path: str) -> bool:
        """Ends the mkvpropedit process of one file, for the case that it hangs.

        Only meant as a last resort on request of the user: the file may be left half-written.
        """
        with self._lock:
            entry = self._running.get(path)
            if entry is None:
                return False
            self._stopped.add(path)
            proc = entry[0]
        try:
            proc.kill()
        except OSError:
            pass
        return True

    def _command(self, option_file: str) -> list[str]:
        return [self.exe, f"@{option_file}"]

    def run(self) -> list[RunResult]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(self._run_one, self.plans))

    def _emit(self, result: RunResult) -> RunResult:
        if self.on_result:
            self.on_result(result)
        return result

    def _run_one(self, plan: FilePlan) -> RunResult:
        path = plan.file.path
        if self._cancel.is_set():
            return self._emit(RunResult(path, RunStatus.CANCELLED, None, ""))
        if not plan.has_work:
            return self._emit(RunResult(path, RunStatus.SKIPPED, None, "No changes."))
        if self.on_start:
            self.on_start(plan)

        fd, opt_path = tempfile.mkstemp(prefix="bmpe_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(["--ui-language", "en", "--output-charset", "UTF-8", path, *plan.args], fh, ensure_ascii=False)
            proc = subprocess.Popen(
                self._command(opt_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            with self._lock:
                self._running[path] = (proc, time.monotonic())
            lines: list[str] = []
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    lines.append(line)
                    if self.on_output:
                        self.on_output(path, line)
                code = proc.wait()
            finally:
                with self._lock:
                    self._running.pop(path, None)
                    stopped = path in self._stopped
            if stopped:
                lines.append("Stopped on request. The file may be incomplete, check it.")
                return self._emit(RunResult(path, RunStatus.STOPPED, code, "\n".join(lines)))
            return self._emit(RunResult(path, status_from_exit(code), code, "\n".join(lines)))
        except OSError as e:
            return self._emit(RunResult(path, RunStatus.ERROR, None, f"Could not start: {e}"))
        finally:
            try:
                os.remove(opt_path)
            except OSError:
                pass
