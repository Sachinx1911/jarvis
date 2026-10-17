"""Teardown (PLAN.md 18.1 item 4): evidence digest -> one model call -> note, document, memory, task.

A teardown is a task ("Teardown <host>", workspace personal) so a receipt exists. The job:
capture (injected; kit.py/browser.py/capture.py do the observing) -> one structured call on route
`teardown` -> `write_teardown` -> the task ends COMPLETED or FAILED with events. One job at a time
(data/xray.lock holds the pid). Egress: only the site address, the user's question and the evidence
digest go to the model route; nothing else leaves the machine.

Truth of a teardown is its note file under workspace/teardowns/ (the document index and the memory
point at it). It ends by archive (`archive_teardown` moves it to workspace/teardowns/archive/),
never by delete (law 2). The document library indexes a copy under projects/teardowns/docs/ so the
note is searchable at once; the workspace file stays the truth.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from jarvis.config import Config
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import LLMRequest, Message
from jarvis.routing.policy import RouteDecision, decide
from jarvis.schema import validate
from jarvis.tasks.store import TaskStore

ROUTE = "teardown"
PROJECT = "teardowns"                 # the document-library project the notes are indexed under
NOTES_DIR = "workspace/teardowns"
MAX_DIGEST_CHARS = 15000
MAX_OUTPUT = 7000                      # max_tokens for the one call (PLAN.md 18.1 item 4)
LOCK_FILE = "xray.lock"
SECTIONS = ("What it is built with", "How the effect is likely done", "Evidence", "Guesses")

TEARDOWN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "spoken": {"type": "string"},
                   "summary": {"type": "string"}, "note": {"type": "string"}},
    "required": ["label", "spoken", "summary", "note"], "additionalProperties": False,
}

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


# ---- the contract with capture.py (the other agent's module); fakes in tests follow it ----

class CaptureLike(Protocol):
    url: str
    host: str
    started_at: str
    finished_at: str
    steps: list
    screenshot: Path | None
    fingerprints: list
    assets: list

    def digest(self, max_chars: int = MAX_DIGEST_CHARS) -> str: ...


CaptureFn = Callable[[str, Path], CaptureLike]   # (url, out_dir) -> Capture


class TeardownError(RuntimeError):
    pass


class TeardownBusy(TeardownError):
    """A second job while one runs."""


@dataclass
class TeardownResult:
    label: str
    spoken: str
    summary: str
    note: str
    note_path: Path | None = None
    screenshot_path: Path | None = None
    memory_id: str | None = None
    task_id: str | None = None
    state: str = ""


@dataclass
class TeardownDeps:
    """Everything a job touches, injected so tests use fakes and nothing imports Chrome or REA here."""
    home: Path
    store: Store
    audit: AuditLog
    tasks: TaskStore
    config: Config
    capture: CaptureFn
    provider_for: Callable[[RouteDecision], Any]
    provider_override: str | None = None
    memory: Any = None                 # MemoryStore, or None to skip the memory entry
    docs: Any = None                   # DocLibrary, or None to skip indexing
    now: Callable[[], datetime] = field(default_factory=lambda: datetime.now)
    pid_alive: Callable[[int], bool] = field(default_factory=lambda: _pid_alive)


# ---- helpers ----

def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or url).lower().strip()
    return re.sub(r"[^a-z0-9.\-]", "-", host) or "site"


def question_language(question: str) -> str:
    return "mr" if _DEVANAGARI.search(question or "") else "en"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows; ask the kernel instead.
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class JobLock:
    """data/xray.lock holds the pid of the running job. A live pid refuses a second job; a stale
    file (its process is gone) is taken over."""

    def __init__(self, data_dir: Path, pid_alive: Callable[[int], bool] = _pid_alive):
        self.path = data_dir / LOCK_FILE
        self.pid_alive = pid_alive
        self._guard = threading.Lock()

    def holder(self) -> int | None:
        try:
            pid = int(self.path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return None
        return pid if self.pid_alive(pid) else None

    def acquire(self) -> None:
        with self._guard:
            other = self.holder()
            if other is not None:
                raise TeardownBusy(f"a teardown is already running (pid {other}); wait for it to finish or "
                                   f"remove {self.path} if that process is gone")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(os.getpid()), encoding="utf-8")

    def release(self) -> None:
        try:
            if self.path.exists() and self.path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.path.unlink()
        except OSError:
            pass


def notes_dir(home: Path) -> Path:
    return home / NOTES_DIR


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise TeardownError(f"too many notes named {path.name}")


def _note_body(result: dict[str, Any]) -> str:
    """The model's note with the four headings guaranteed, in order; a missing one says so."""
    text = str(result.get("note", "")).strip()
    have = {m.group(1).strip() for m in re.finditer(r"^##\s+(.+?)\s*$", text, re.M)}
    missing = [s for s in SECTIONS if s not in have]
    for s in missing:
        text += f"\n\n## {s}\n- (nothing recorded under this heading)"
    return text.strip()


def render_note(capture: CaptureLike, result: dict[str, Any], question: str, lang: str,
                screenshot_rel: str | None, when: datetime) -> str:
    head = [f"# Teardown: {capture.host}", "",
            f"- URL: {capture.url}", f"- Date: {when:%Y-%m-%d %H:%M}",
            f"- Question ({lang}): {question or '(none)'}",
            f"- Label: {result.get('label', '')}",
            f"- Screenshot: {screenshot_rel or '(none)'}", "",
            "## Summary", str(result.get("summary", "")).strip(), "",
            "## Spoken", str(result.get("spoken", "")).strip(), "",
            _note_body(result), "",
            "## Capture steps"]
    for s in capture.steps:
        who, ok, name, detail = getattr(s, "who", "?"), getattr(s, "ok", False), getattr(s, "name", "?"), getattr(s, "detail", "")
        head.append(f"- [{'x' if ok else '!'}] {name} ({who}){': ' + str(detail) if detail else ''}")
    head += ["", "## Digest", "", "```", capture.digest(MAX_DIGEST_CHARS), "```", ""]
    return "\n".join(head)


# ---- writing: note, screenshot, document index, memory ----

def write_teardown(capture: CaptureLike, result: dict[str, Any], home: Path, store: Store, audit: AuditLog,
                   question_lang: str = "en", question: str = "", memory: Any = None, docs: Any = None,
                   now: datetime | None = None) -> TeardownResult:
    when = now or datetime.now()
    folder = notes_dir(home)
    assets = folder / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    stem = f"{capture.host}-{when:%Y-%m-%d}"
    note_path = _unique(folder / f"{stem}.md")

    screenshot_path: Path | None = None
    screenshot_rel = None
    shot = capture.screenshot
    if shot and Path(shot).is_file():
        screenshot_path = _unique(assets / f"{note_path.stem}{Path(shot).suffix or '.png'}")
        shutil.copyfile(shot, screenshot_path)
        screenshot_rel = f"assets/{screenshot_path.name}"

    text = render_note(capture, result, question, question_lang, screenshot_rel, when)
    note_path.write_text(text, encoding="utf-8")

    # The document library reads projects/<name>/docs/: a copy goes there so the note is searchable
    # at once (the workspace file is the truth; archive_teardown moves both).
    indexed = False
    if docs is not None:
        lib_dir = docs.docs_dir(PROJECT)
        lib_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(note_path, lib_dir / note_path.name)
        docs.index(PROJECT)
        indexed = True

    out = TeardownResult(str(result.get("label", "")), str(result.get("spoken", "")),
                         str(result.get("summary", "")), text, note_path, screenshot_path)
    if memory is not None:
        out.memory_id = _remember(capture, out, memory, audit)
    audit.write("teardown_written", host=capture.host, url=capture.url, note=str(note_path),
                screenshot=str(screenshot_path) if screenshot_path else None, indexed=indexed,
                memory_id=out.memory_id, language=question_lang)
    return out


def _remember(capture: CaptureLike, out: TeardownResult, memory: Any, audit: AuditLog) -> str | None:
    """A fact with subject "reference" ("reference" is not a memory type; adding one would change
    every type-keyed folder). Observed: the note is measured evidence; the model's reading of it is
    medium confidence. Never raises: the note is written already."""
    from jarvis.memory.model import Memory
    from jarvis.memory.store import MemoryRejected

    try:
        mem = Memory(name=f"Teardown: {capture.host}", type="fact", subject="reference",
                     body=f"{out.summary}\n\nTeardown note: {out.note_path}",
                     summary_en=out.summary[:200], keywords=f"teardown REA x-ray {capture.host} {out.label}",
                     evidence=f"teardown note {out.note_path}", source="observed", confidence="medium",
                     workspace="personal", scope=f"project:{PROJECT}")
        return memory.save(mem).id
    except MemoryRejected as e:
        audit.write("teardown_not_remembered", host=capture.host, reason=str(e)[:200])
    except Exception as e:  # noqa: BLE001
        audit.write("teardown_not_remembered", host=capture.host, reason=f"{type(e).__name__}: {e}"[:200])
    return None


def archive_teardown(path: Path, home: Path, docs: Any = None) -> Path:
    """End (law 2): the note moves to workspace/teardowns/archive/; its library copy leaves docs/
    (to projects/teardowns/archive/) and the index drops it. Nothing is deleted."""
    path = Path(path)
    folder = notes_dir(home)
    if not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
        raise TeardownError(f"{path} is not a teardown note under {folder}")
    archive = folder / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    target = _unique(archive / path.name)
    shutil.move(str(path), str(target))
    if docs is not None:
        copy = docs.docs_dir(PROJECT) / path.name
        if copy.is_file():
            lib_archive = docs.docs_dir(PROJECT).parent / "archive"
            lib_archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(copy), str(_unique(lib_archive / path.name)))
        docs.index(PROJECT)
    return target


def latest_note(home: Path) -> Path | None:
    folder = notes_dir(home)
    if not folder.is_dir():
        return None
    notes = [p for p in folder.glob("*.md") if p.is_file()]
    return max(notes, key=lambda p: p.stat().st_mtime) if notes else None


def note_summary(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## Summary\s*\n(.*?)(?=\n## |\Z)", text, re.S | re.M)
    return (m.group(1).strip() if m else "").strip() or "(no summary)"


# ---- the job ----

def _ask_model(deps: TeardownDeps, url: str, question: str, digest: str, lang: str, task_id: str) -> dict[str, Any]:
    d = decide(deps.config, ROUTE, deps.provider_override)
    system = (PROMPTS_DIR / "teardown.md").read_text(encoding="utf-8")
    user = (f"Site: {url}\nQuestion ({'Marathi' if lang == 'mr' else 'English'}): {question or 'What is it built with and how is it done?'}\n\n"
            f"Evidence digest (every line says who saw it):\n{digest}")
    req = LLMRequest(route=ROUTE, model=d.model, system=system, messages=[Message.text("user", user)],
                     reasoning=d.effort, response_schema=TEARDOWN_SCHEMA, max_output=MAX_OUTPUT,  # type: ignore[arg-type]
                     task_id=task_id, privacy_classes=frozenset({"P1"}))
    res = deps.provider_for(d).structured(req, TEARDOWN_SCHEMA)
    deps.store.record_usage(None, ROUTE, res.response, task_id=task_id, workspace="personal")
    deps.audit.write("model_call", route=ROUTE, provider=res.response.provider, model=res.response.model,
                     input_tokens=res.response.usage.input_tokens, output_tokens=res.response.usage.output_tokens,
                     valid=res.valid, task_id=task_id)
    if not res.valid or not validate(res.data, TEARDOWN_SCHEMA):
        raise TeardownError("the model did not return a valid teardown (label, spoken, summary, note)")
    return res.data  # type: ignore[return-value]


def _receipt(deps: TeardownDeps, task_id: str, result: TeardownResult, error: str | None) -> Path:
    """A small receipt from the task's own facts (jarvis.tasks.receipt needs a TaskRunner, which a
    teardown does not have): state, model calls and the note path."""
    task = deps.tasks.get(task_id)
    usage = deps.tasks.usage(task_id)
    lines = [f"{task.state if task else '?'} · {task_id} · {task.title if task else ''} · {usage['calls']} model calls",
             "", f"Note: {result.note_path or '(none)'}", f"Label: {result.label or '(none)'}", "",
             result.summary or "", ""]
    if error:
        lines += [f"Error: {error}", ""]
    lines += ["Models: " + (", ".join(usage["models"]) or "none"),
              f"Tokens: {usage['input_tokens']:,} in, {usage['output_tokens']:,} out"]
    path = deps.tasks.folder(task_id) / "receipt.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    deps.tasks.event(task_id, "receipt", str(path))
    return path


def run_teardown(url: str, question: str, deps: TeardownDeps) -> TeardownResult:
    """One teardown job, start to end. Raises TeardownBusy when another job holds the lock; any other
    failure ends the task FAILED and raises TeardownError."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise TeardownError(f"not a web address: {url!r}")
    host = host_of(url)
    lang = question_language(question)
    lock = JobLock(deps.home / "data", deps.pid_alive)
    try:
        lock.acquire()
    except TeardownBusy as e:
        deps.audit.write("teardown_refused", url=url, reason=str(e)[:200])
        raise
    task = deps.tasks.create(f"Teardown of {url}: {question or 'what it is built with and how'}",
                             title=f"Teardown {host}", state="PLANNED", workspace="personal")
    deps.tasks.set_state(task.id, "RUNNING", "teardown")
    deps.audit.write("teardown_started", task_id=task.id, url=url, host=host, language=lang)
    result = TeardownResult("", "", "", "", task_id=task.id)
    try:
        out_dir = deps.home / "data" / "xray" / task.id
        out_dir.mkdir(parents=True, exist_ok=True)
        capture = deps.capture(url, out_dir)
        deps.tasks.event(task.id, "capture", {"host": capture.host, "steps": len(capture.steps),
                                              "fingerprints": len(capture.fingerprints), "assets": len(capture.assets),
                                              "screenshot": str(capture.screenshot) if capture.screenshot else None})
        digest = capture.digest(MAX_DIGEST_CHARS)[:MAX_DIGEST_CHARS]
        data = _ask_model(deps, url, question, digest, lang, task.id)
        deps.tasks.set_state(task.id, "VERIFYING", "writing the note")
        written = write_teardown(capture, data, deps.home, deps.store, deps.audit, lang, question,
                                 memory=deps.memory, docs=deps.docs, now=deps.now())
        written.task_id = task.id
        result = written
        deps.tasks.event(task.id, "teardown", {"note": str(written.note_path), "label": written.label,
                                               "memory_id": written.memory_id})
        deps.tasks.set_state(task.id, "COMPLETED", "teardown written")
        result.state = "COMPLETED"
        _receipt(deps, task.id, result, None)
        deps.audit.write("teardown_finished", task_id=task.id, host=host, note=str(written.note_path),
                         label=written.label)
        return result
    except Exception as e:  # noqa: BLE001 (ProviderError, RoutingError, TeardownError, OSError: all end the task FAILED)
        reason = f"{type(e).__name__}: {e}"[:300]
        deps.tasks.update(task.id, last_error=reason)
        current = deps.tasks.get(task.id)
        if current and current.state not in ("FAILED", "COMPLETED", "CANCELLED"):
            deps.tasks.set_state(task.id, "FAILED", reason)
        result.state = "FAILED"
        _receipt(deps, task.id, result, reason)
        deps.audit.write("teardown_failed", task_id=task.id, host=host, reason=reason)
        raise TeardownError(reason) from e
    finally:
        lock.release()
