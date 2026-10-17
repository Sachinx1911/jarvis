"""Phase 9 part G: the teardown job with a fake capture and a fake provider. No Chrome, no REA, no model."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.docs.library import DocLibrary
from jarvis.memory.store import MemoryStore
from jarvis.providers.base import ProviderError
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import decide
from jarvis.tasks.store import TaskStore
from jarvis.xray import teardown as td
from jarvis.xray.teardown import (
    SECTIONS, TEARDOWN_SCHEMA, JobLock, TeardownBusy, TeardownDeps, TeardownError, archive_teardown,
    latest_note, note_summary, run_teardown, write_teardown,
)

NOW = datetime(2026, 10, 17, 11, 30)


# ---- fakes that follow capture.py's contract (clearly fakes: nothing is observed) ----

@dataclass
class Step:
    name: str
    who: str
    ok: bool
    detail: str = ""


@dataclass
class Fingerprint:
    library: str
    version: str
    evidence: str
    who: str


@dataclass
class Asset:
    kind: str
    url: str
    bytes: int


@dataclass
class FakeCapture:
    url: str
    host: str
    started_at: str = "2026-10-17T11:30:00"
    finished_at: str = "2026-10-17T11:31:00"
    steps: list = field(default_factory=lambda: [Step("open page", "Jarvis", True, "readyState complete"),
                                                 Step("inspect-web-page", "REA", True, "12 nodes")])
    screenshot: Path | None = None
    fingerprints: list = field(default_factory=lambda: [Fingerprint("three.js", "r165", "THREE.REVISION", "Jarvis"),
                                                        Fingerprint("gsap", "3.12.5", "licence banner", "Jarvis")])
    assets: list = field(default_factory=lambda: [Asset("script", "https://igloo.inc/app.js", 412000)])

    def digest(self, max_chars: int = 15000) -> str:
        lines = ["| who | what |", "| REA | inspect-web-page: 12 nodes, canvas present |"]
        lines += [f"| {f.who} | {f.library} {f.version} ({f.evidence}) |" for f in self.fingerprints]
        lines += [f"| Jarvis | asset {a.kind} {a.url} {a.bytes} bytes |" for a in self.assets]
        return "\n".join(lines)[:max_chars]


MODEL_ANSWER = {
    "label": "Three.js + GSAP scroll site",
    "spoken": "It is a Three.js scene driven by GSAP scroll triggers.",
    "summary": "Built with Three.js r165 and GSAP 3.12.5. The scroll effect is likely a GSAP timeline moving the camera.",
    "note": "## What it is built with\n- Three.js r165 (Jarvis saw THREE.REVISION)\n- GSAP 3.12.5 (Jarvis saw the licence banner)\n\n"
            "## How the effect is likely done\n- likely a GSAP ScrollTrigger timeline moving a Three.js camera\n\n"
            "## Evidence\n- REA: inspect-web-page found a canvas\n- Jarvis: three.js r165 from THREE.REVISION\n\n"
            "## Guesses\n- guess: postprocessing bloom on the canvas",
}


@pytest.fixture
def env(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    yield isolated, store
    store.close()


def _deps(env, provider=None, capture=None, **kw):
    home, store = env
    audit = AuditLog(home / "data" / "audit.jsonl")
    provider = provider or FakeProvider(script=[{"json": MODEL_ANSWER}])

    def do_capture(url, out_dir):
        if capture is not None:
            return capture(url, out_dir)
        shot = Path(out_dir) / "screenshot.png"
        shot.write_bytes(b"\x89PNG fake")
        return FakeCapture(url, "igloo.inc", screenshot=shot)

    return TeardownDeps(home=home, store=store, audit=audit, tasks=TaskStore(store, home / "data" / "tasks"),
                        config=load_config(), capture=do_capture, provider_for=lambda d: provider,
                        provider_override="fake", memory=MemoryStore(home, store), docs=DocLibrary(home, store),
                        now=lambda: NOW, **kw), provider


def _audit(home):
    return [json.loads(l) for l in (home / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- route ----

def test_teardown_route_is_opus_high_structured():
    d = decide(load_config(), "teardown")
    assert (d.provider, d.model, d.effort) == ("claude_code", "claude-opus-5-5", "high")
    spec = load_config().routing["routes"]["teardown"]
    assert spec["needs"] == ["structured_output"] and spec["max_privacy"] == "P1" and spec["cloud_fallback"] == "never"


# ---- the whole job ----

def test_run_teardown_writes_note_document_memory_and_task(env):
    home, store = env
    deps, provider = _deps(env)
    res = run_teardown("https://igloo.inc", "how does igloo.inc do that scroll effect", deps)

    # the note, with all four sections and the capture facts
    assert res.state == "COMPLETED" and res.label == MODEL_ANSWER["label"]
    assert res.note_path == home / "workspace" / "teardowns" / "igloo.inc-2026-10-17.md"
    text = res.note_path.read_text(encoding="utf-8")
    for s in SECTIONS:
        assert f"## {s}" in text
    assert "## Summary" in text and MODEL_ANSWER["summary"] in text
    assert "| REA | inspect-web-page" in text and "inspect-web-page (REA)" in text
    # the screenshot copied next to it
    assert res.screenshot_path == home / "workspace" / "teardowns" / "assets" / "igloo.inc-2026-10-17.png"
    assert res.screenshot_path.read_bytes() == b"\x89PNG fake" and "Screenshot: assets/igloo.inc-2026-10-17.png" in text
    # indexed as project teardowns and searchable at once
    docs = DocLibrary(home, store)
    assert [d.file for d in docs.documents("teardowns")] == ["igloo.inc-2026-10-17.md"]
    hits = docs.search("GSAP scroll camera", project="teardowns")
    assert hits and hits[0].file == "igloo.inc-2026-10-17.md"
    # a memory: fact with subject reference, observed, personal, pointing at the note
    mem = MemoryStore(home, store).get(res.memory_id)
    assert mem.type == "fact" and mem.subject == "reference" and mem.source == "observed"
    assert mem.workspace == "personal" and str(res.note_path) in mem.body and "igloo.inc" in mem.keywords
    assert MemoryStore(home, store).search("igloo teardown", workspace="personal")[0].memory.id == res.memory_id
    # the task: completed, with the events and a receipt
    task = deps.tasks.get(res.task_id)
    assert task.state == "COMPLETED" and task.title == "Teardown igloo.inc" and task.workspace == "personal"
    kinds = [e["kind"] for e in deps.tasks.events(res.task_id)]
    assert kinds == ["created", "state", "capture", "state", "teardown", "state", "receipt"]
    event = next(e for e in deps.tasks.events(res.task_id) if e["kind"] == "teardown")
    assert event["detail"]["note"] == str(res.note_path) and event["detail"]["memory_id"] == res.memory_id
    receipt = (home / "data" / "tasks" / res.task_id / "receipt.md").read_text(encoding="utf-8")
    assert "COMPLETED" in receipt and str(res.note_path) in receipt and "1 model calls" in receipt
    assert deps.tasks.usage(res.task_id)["calls"] == 1
    # the audit trail, in order
    events = [e["event"] for e in _audit(home)]
    for name in ("teardown_started", "model_call", "teardown_written", "teardown_finished"):
        assert name in events
    assert events.index("teardown_started") < events.index("teardown_written") < events.index("teardown_finished")
    # the lock is gone
    assert not (home / "data" / "xray.lock").exists()


def test_egress_only_url_question_and_digest_leave(env):
    home, store = env
    MemoryStore(home, store).save(__import__("jarvis.memory.model", fromlist=["Memory"]).Memory(
        name="private fact", body="Sachin's secret plan", evidence="said so"))
    deps, provider = _deps(env)
    run_teardown("https://igloo.inc", "what is it built with", deps)
    assert len(provider.requests) == 1
    req = provider.requests[0]
    assert req.route == "teardown" and req.max_output >= 7000 and req.response_schema == TEARDOWN_SCHEMA
    assert req.privacy_classes == frozenset({"P1"})
    sent = req.messages[0].text_content()
    digest = FakeCapture("https://igloo.inc", "igloo.inc").digest()
    assert "https://igloo.inc" in sent and digest in sent and "what is it built with" in sent
    # nothing else: strip the three allowed things and the fixed framing, and nothing meaningful is left
    rest = sent.replace(digest, "").replace("https://igloo.inc", "").replace("what is it built with", "")
    assert "secret plan" not in rest and "memory" not in rest.lower()
    assert set(rest.split()) <= {"Site:", "Question", "(English):", "Evidence", "digest", "(every", "line", "says",
                                 "who", "saw", "it):"}
    assert "secret plan" not in req.system


def test_marathi_question_is_marked_and_the_note_records_it(env):
    deps, _ = _deps(env)
    res = run_teardown("https://igloo.inc", "igloo.inc कसं बनवलंय", deps)
    assert "Question (mr): igloo.inc कसं बनवलंय" in res.note_path.read_text(encoding="utf-8")
    assert "Question (Marathi)" in deps.provider_for(None).requests[0].messages[0].text_content()
    assert any(e["event"] == "teardown_started" and e["language"] == "mr" for e in _audit(deps.home))


def test_failed_model_call_fails_the_task_and_audits(env):
    class Broken(FakeProvider):
        def structured(self, req, schema):
            raise ProviderError("cli died", kind="server")

    deps, _ = _deps(env, provider=Broken())
    with pytest.raises(TeardownError, match="cli died"):
        run_teardown("https://igloo.inc", "how", deps)
    tasks = deps.tasks.list(include_final=True)
    assert len(tasks) == 1 and tasks[0].state == "FAILED" and "cli died" in tasks[0].last_error
    assert not list((deps.home / "workspace" / "teardowns").glob("*.md")) if (deps.home / "workspace" / "teardowns").exists() else True
    assert (deps.home / "data" / "tasks" / tasks[0].id / "receipt.md").read_text(encoding="utf-8").startswith("FAILED")
    events = [e for e in _audit(deps.home) if e["event"] == "teardown_failed"]
    assert len(events) == 1 and "cli died" in events[0]["reason"]
    assert not (deps.home / "data" / "xray.lock").exists()   # released for the next job


def test_invalid_model_output_fails_the_task(env):
    deps, _ = _deps(env, provider=FakeProvider(script=[{"json": {"label": "x"}}]))
    with pytest.raises(TeardownError, match="valid teardown"):
        run_teardown("https://igloo.inc", "how", deps)
    assert deps.tasks.list(include_final=True)[0].state == "FAILED"


def test_capture_failure_fails_the_task(env):
    def boom(url, out_dir):
        raise RuntimeError("chrome did not start")

    deps, provider = _deps(env, capture=boom)
    with pytest.raises(TeardownError, match="chrome did not start"):
        run_teardown("https://igloo.inc", "how", deps)
    assert provider.requests == []   # no model call without evidence
    assert deps.tasks.list(include_final=True)[0].state == "FAILED"


def test_bad_address_is_refused_before_any_task(env):
    deps, _ = _deps(env)
    with pytest.raises(TeardownError, match="not a web address"):
        run_teardown("igloo", "how", deps)
    assert deps.tasks.list(include_final=True) == []


# ---- one job at a time ----

def test_lock_refuses_a_second_job_while_the_first_runs(env):
    home, _ = env
    lock = home / "data" / "xray.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")   # "another" live job: this very process
    deps, provider = _deps(env)
    with pytest.raises(TeardownBusy, match="already running"):
        run_teardown("https://igloo.inc", "how", deps)
    assert provider.requests == [] and deps.tasks.list(include_final=True) == []
    assert any(e["event"] == "teardown_refused" for e in _audit(home))
    assert lock.read_text(encoding="utf-8") == str(os.getpid())   # the other job's lock is left alone


def test_stale_lock_is_taken_over(env):
    home, _ = env
    lock = home / "data" / "xray.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999999", encoding="utf-8")
    deps, _ = _deps(env, pid_alive=lambda pid: False)
    assert run_teardown("https://igloo.inc", "how", deps).state == "COMPLETED"
    assert not lock.exists()


def test_job_lock_reports_its_holder(env):
    home, _ = env
    lock = JobLock(home / "data", pid_alive=lambda pid: pid == 4242)
    assert lock.holder() is None
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text("4242", encoding="utf-8")
    assert lock.holder() == 4242
    lock.path.write_text("garbage", encoding="utf-8")
    assert lock.holder() is None


# ---- write_teardown on its own, archive, last ----

def test_write_teardown_fills_missing_sections_and_numbers_duplicates(env):
    home, store = env
    audit = AuditLog(home / "data" / "audit.jsonl")
    thin = {**MODEL_ANSWER, "note": "## What it is built with\n- Three.js"}
    cap = FakeCapture("https://igloo.inc", "igloo.inc")
    first = write_teardown(cap, thin, home, store, audit, "en", "q", now=NOW)
    second = write_teardown(cap, thin, home, store, audit, "en", "q", now=NOW)
    assert first.note_path.name == "igloo.inc-2026-10-17.md" and second.note_path.name == "igloo.inc-2026-10-17-2.md"
    text = first.note_path.read_text(encoding="utf-8")
    for s in SECTIONS:
        assert f"## {s}" in text
    assert "(nothing recorded under this heading)" in text and "Screenshot: (none)" in text
    assert first.memory_id is None and first.screenshot_path is None   # no memory store, no screenshot given
    assert latest_note(home) in (first.note_path, second.note_path)
    assert note_summary(first.note_path) == MODEL_ANSWER["summary"]


def test_archive_moves_the_note_and_drops_it_from_the_index(env):
    home, store = env
    deps, _ = _deps(env)
    res = run_teardown("https://igloo.inc", "how", deps)
    docs = DocLibrary(home, store)
    moved = archive_teardown(res.note_path, home, docs)
    assert moved == home / "workspace" / "teardowns" / "archive" / "igloo.inc-2026-10-17.md" and moved.is_file()
    assert not res.note_path.exists() and latest_note(home) is None
    assert docs.documents("teardowns") == []
    assert (home / "projects" / "teardowns" / "archive" / "igloo.inc-2026-10-17.md").is_file()   # moved, not deleted
    with pytest.raises(TeardownError, match="not a teardown note"):
        archive_teardown(home / "elsewhere.md", home)


def test_memory_rejection_keeps_the_note(env, monkeypatch):
    home, store = env
    deps, _ = _deps(env)
    secret = {**MODEL_ANSWER, "summary": "The API key is sk-ant-abcdefghijklmnop1234567890 in the bundle."}
    deps.provider_for = lambda d: FakeProvider(script=[{"json": secret}])
    res = run_teardown("https://igloo.inc", "how", deps)
    assert res.state == "COMPLETED" and res.note_path.is_file() and res.memory_id is None
    assert any(e["event"] == "teardown_not_remembered" for e in _audit(home))


def test_host_of_and_language():
    assert td.host_of("https://www.Stripe.com/pricing") == "www.stripe.com"
    assert td.host_of("http://localhost:3000/") == "localhost"
    assert td.question_language("how") == "en" and td.question_language("कसं") == "mr"
