"""Background jobs started from the dashboard (evaluation run, Google sign-in, schedule
run-now). One job per kind at a time; the browser polls the status. Results are kept
small and never contain secrets (callers return plain summaries)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.control.audit import AuditLog


@dataclass
class Job:
    kind: str
    key: str
    started: float = field(default_factory=time.time)
    finished: float | None = None
    status: str = "running"  # running | done | error
    result: Any = None
    error: str = ""

    def public(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "status": self.status, "started": self.started,
                "finished": self.finished, "result": self.result, "error": self.error}


class JobBusy(RuntimeError):
    pass


class Jobs:
    def __init__(self, audit: AuditLog):
        self.audit = audit
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}

    def start(self, kind: str, fn: Callable[[], Any], key: str = "") -> Job:
        with self._lock:
            old = self._jobs.get(kind)
            if old and old.status == "running":
                raise JobBusy(f"{kind} is already running")
            job = Job(kind, key)
            self._jobs[kind] = job

        def run() -> None:
            try:
                job.result = fn()
                job.status = "done"
            except Exception as e:  # reported to the browser; the server keeps running
                job.status, job.error = "error", f"{type(e).__name__}: {e}"
                self.audit.write("dashboard_job_error", kind=kind, key=key, error=type(e).__name__)
            finally:
                job.finished = time.time()

        t = threading.Thread(target=run, name=f"job-{kind}", daemon=True)
        self._threads[kind] = t
        t.start()
        return job

    def get(self, kind: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(kind)
        return job.public() if job else None

    def join(self, kind: str, timeout: float | None = None) -> None:
        t = self._threads.get(kind)
        if t:
            t.join(timeout)
