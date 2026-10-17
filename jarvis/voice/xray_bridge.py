"""Voice -> teardown: what the voice loop says when a teardown route matches.

Thin on purpose: the kit, Chrome and REA modules are imported only when a job starts, inside a
try, so a missing kit never breaks voice. "This site" reads the front Chrome tab's address
(jarvis.xray.front_tab) and shows it on screen for a typed yes before it is used (T1).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable, TextIO

from jarvis.control.audit import AuditLog
from jarvis.xray.front_tab import front_tab
from jarvis.xray.spoken import parse_spoken_address
from jarvis.xray.teardown import TeardownBusy, TeardownError, host_of, latest_note, note_summary, run_teardown

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


class VoiceXray:
    def __init__(self, session: Any, home: Path, audit: AuditLog, out: TextIO, inp: TextIO,
                 deps_factory: Callable[[], Any] | None = None, diag: Callable[[], dict] | None = None,
                 front: Callable[[], Any] | None = None, runner: Callable[..., None] | None = None):
        self.session = session
        self.home = home
        self.audit = audit
        self.out = out
        self.inp = inp
        self._deps_factory = deps_factory
        self._diag = diag
        self._front = front or front_tab
        self._runner = runner or self._in_thread
        self.jobs: list[threading.Thread] = []

    # ---- the two spoken answers ----

    def last(self) -> str:
        path = latest_note(self.home)
        if path is None:
            return "There is no teardown yet. Say: reverse engineer, and a site address."
        return f"The last teardown is {path.stem}. {note_summary(path)}"

    def start(self, url: str | None, question: str) -> str:
        marathi = bool(_DEVANAGARI.search(question))
        if url == "this site":
            tab = self._front()
            if not tab.url:
                return tab.reason
            print(f"Front tab address: {tab.url} ({tab.reason})", file=self.out)
            self.out.write("Tear down this address? [y/N] ")
            self.out.flush()
            if self.inp.readline().strip().lower() not in ("y", "yes", "ho", "हो"):
                self.audit.write("teardown_declined", url=tab.url, how="front tab not confirmed")
                return "Left it. Say the address if you want a different one."
            url = tab.url
        if not url:
            return ("कोणती साइट? पत्ता सांगा, जसं: igloo dot inc." if marathi
                    else "Which site? Say the address, like: igloo dot inc.")
        url = parse_spoken_address(url) or url
        diag = (self._diag or _default_diag)()
        if not diag.get("ready"):
            from jarvis.xray.live import problems_text

            return f"The teardown kit is not ready: {problems_text(diag)}. Run: jarvis xray diag"
        try:
            deps = (self._deps_factory or self._default_deps)()
        except ImportError as e:
            return f"The teardown kit is not available: {e}"
        host = host_of(url)
        self._runner(url, question, deps)
        return (f"{host} चं teardown सुरू करतोय. झालं की note workspace/teardowns मध्ये असेल." if marathi
                else f"Starting the teardown of {host}. The note lands in workspace/teardowns when it is done.")

    # ---- plumbing ----

    def _in_thread(self, url: str, question: str, deps: Any) -> None:
        def job() -> None:
            try:
                res = run_teardown(url, question, deps)
                print(f"\nTeardown done: {res.note_path}\n{res.spoken}", file=self.out)
            except TeardownBusy as e:
                print(f"\nTeardown refused: {e}", file=self.out)
            except TeardownError as e:
                print(f"\nTeardown failed: {e}", file=self.out)

        t = threading.Thread(target=job, name="jarvis-teardown", daemon=True)
        self.jobs.append(t)
        t.start()

    def _default_deps(self) -> Any:
        from jarvis.xray.live import live_deps

        store = getattr(self.session, "store", None)
        config = getattr(self.session, "config", None)
        if store is None:
            raise ImportError("the voice session has no store to write the teardown with")
        return live_deps(self.home, store, self.audit, config, memory=getattr(self.session, "memory", None))


def _default_diag() -> dict:
    from jarvis.xray.live import kit_diag

    return kit_diag()
