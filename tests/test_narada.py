"""Narada between lokas (PLAN.md 27.5 item 6): one office asks another through Jarvis, logged; the
asked office runs it as its own task; only the result and the deliverable file cross back, never
memory. Archive, never delete; delete_forever only on an archived row."""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.cli import main
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.tasks.store import TaskStore
from jarvis.workspaces.model import WorkspaceError
from jarvis.workspaces.narada import NaradaRefused, RequestStore, deliver_for_task
from jarvis.workspaces.store import WorkspaceStore


class Setup:
    def __init__(self, home: Path):
        self.home = home
        self.ws = WorkspaceStore(home)
        self.ws.create("acme", "Acme Ltd")
        self.ws.create("globex", "Globex")
        self.store = Store(home / "data" / "jarvis.db")
        self.tasks = TaskStore(self.store, home / "data" / "tasks")
        self.audit = AuditLog(home / "data" / "audit.jsonl")
        self.requests = RequestStore(self.store.conn, home, self.audit)

    def ally(self, slug: str, *allies: str) -> None:
        self.ws.save(replace(self.ws.get(slug), allies=allies))

    def audit_text(self) -> str:
        p = self.home / "data" / "audit.jsonl"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def finish(self, task_id: str, state: str = "COMPLETED", body: str | None = "# Report\n\nThe answer is 42.\n"):
        """Walk a task to a final state the way the orchestrator would, with a deliverable in its folder."""
        if self.tasks.get(task_id).state == "BACKLOG":
            self.tasks.set_state(task_id, "PLANNED")
        if self.tasks.get(task_id).state == "PLANNED":
            self.tasks.set_state(task_id, "RUNNING")
        self.tasks.update(task_id, plan={"deliverable": {"filename": "report.md"}})
        if body is not None:
            (self.home / "data" / "tasks" / task_id / "report.md").write_text(body, encoding="utf-8")
        if state == "COMPLETED":
            self.tasks.set_state(task_id, "VERIFYING")
            self.tasks.set_state(task_id, "COMPLETED")
        elif state == "FAILED":
            self.tasks.update(task_id, last_error="the web was down")
            self.tasks.set_state(task_id, "FAILED", "the web was down")
        else:
            self.tasks.set_state(task_id, state)
        return self.tasks.get(task_id)


@pytest.fixture
def s(isolated):
    setup = Setup(isolated)
    yield setup
    setup.store.close()


# ---- the store ----

def test_ask_creates_a_task_in_the_asked_office_and_audits(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "draft the vendor brief", s.tasks, source="cli")
    assert r.id == "lr-001" and r.state == "requested" and r.from_workspace == "acme" and r.to_workspace == "globex"
    task = s.tasks.get(r.task_id)
    assert task.workspace == "globex" and task.owner == "narada:acme" and task.title.startswith("Request from acme:")
    assert any(e["kind"] == "loka_request" for e in s.tasks.events(task.id))
    assert "loka_request_made" in s.audit_text() and '"source": "cli"' in s.audit_text()
    assert s.requests.get("lr-001").goal == "draft the vendor brief"
    assert s.requests.for_task(task.id).id == "lr-001"


def test_a_company_may_ask_only_its_allies(s):
    with pytest.raises(NaradaRefused, match="acme may not ask globex: add it to allies in workspace.yaml"):
        s.requests.ask("acme", "globex", "anything", s.tasks)
    assert s.requests.list() == [] and s.tasks.list() == []   # a refused request leaves nothing behind
    s.ally("acme", "globex")
    assert s.requests.ask("acme", "globex", "anything", s.tasks).state == "requested"
    with pytest.raises(NaradaRefused):   # allies are one way
        s.requests.ask("globex", "acme", "back", s.tasks)


def test_personal_may_ask_any_office_but_nobody_asks_itself_or_a_closed_office(s):
    assert s.requests.ask("personal", "acme", "a", s.tasks).to_workspace == "acme"
    assert s.requests.ask("personal", "globex", "b", s.tasks).to_workspace == "globex"
    with pytest.raises(NaradaRefused, match="cannot ask itself"):
        s.requests.ask("personal", "personal", "c", s.tasks)
    with pytest.raises(WorkspaceError, match="no workspace 'nope'"):
        s.requests.ask("personal", "nope", "c", s.tasks)
    s.ws.archive("globex")
    with pytest.raises(NaradaRefused, match="archived"):
        s.requests.ask("personal", "globex", "d", s.tasks)
    with pytest.raises(NaradaRefused, match="say what"):
        s.requests.ask("personal", "acme", "   ", s.tasks)


def test_deliver_copies_only_the_deliverable_and_writes_no_memory(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "write the report", s.tasks)
    task = s.finish(r.task_id)
    # something private of the asked office sits next to the deliverable; it must not cross
    (s.home / "data" / "tasks" / task.id / "notes.md").write_text("globex secrets", encoding="utf-8")
    src = s.home / "data" / "tasks" / task.id / "report.md"
    done = s.requests.deliver(r.id, task, "Report written.", str(src))
    assert done.state == "done" and done.result == "Report written."
    inbox = s.home / "data" / "workspaces" / "acme" / "inbox"
    assert sorted(p.name for p in inbox.iterdir()) == [f"{task.id}-report.md"]
    assert Path(done.deliverable).read_text(encoding="utf-8").endswith("The answer is 42.\n")
    assert s.store.conn.execute("SELECT COUNT(*) FROM memory_index").fetchone()[0] == 0
    assert not (s.home / "memory").exists() or not list((s.home / "memory").rglob("*.md"))
    assert "loka_request_delivered" in s.audit_text()
    assert s.requests.for_task(task.id) is None   # delivered: no longer open


def test_deliver_refuses_a_file_outside_the_task_folder(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "x", s.tasks)
    task = s.finish(r.task_id)
    outside = s.home / "data" / "workspaces" / "globex" / "workspace.yaml"
    done = s.requests.deliver(r.id, task, "ok", str(outside))
    assert done.state == "done" and done.deliverable is None
    assert not (s.home / "data" / "workspaces" / "acme" / "inbox").exists()
    assert "loka_request_deliverable_refused" in s.audit_text()


def test_deliver_marks_failed_with_the_task_error_and_cancelled_as_declined(s):
    s.ally("acme", "globex")
    r1 = s.requests.ask("acme", "globex", "a", s.tasks)
    failed = s.requests.deliver(r1.task_id, s.finish(r1.task_id, "FAILED"))   # by task id too
    assert failed.id == r1.id and failed.state == "failed" and failed.result == "the web was down"
    r2 = s.requests.ask("acme", "globex", "b", s.tasks)
    cancelled = s.requests.deliver(r2.id, s.finish(r2.task_id, "CANCELLED"))
    assert cancelled.state == "declined" and "cancelled" in cancelled.result


def test_decline_start_and_list(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "a", s.tasks)
    other = s.requests.ask("personal", "globex", "b", s.tasks)
    assert s.requests.start(r.id).state == "running"
    assert s.requests.start(r.id).state == "running"   # idempotent
    d = s.requests.decline(r.id, "not our duty")
    assert d.state == "declined" and d.result == "not our duty"
    with pytest.raises(WorkspaceError, match="already declined"):
        s.requests.decline(r.id, "again")
    assert "loka_request_declined" in s.audit_text()
    assert [x.id for x in s.requests.list("acme")] == [r.id]
    assert [x.id for x in s.requests.list("globex")] == [r.id, other.id]
    assert [x.id for x in s.requests.list("personal")] == [other.id]
    assert [x.id for x in s.requests.list()] == [r.id, other.id]
    assert "[declined]" in r.line() or "[declined]" in d.line()
    with pytest.raises(WorkspaceError, match="no request"):
        s.requests.decline("lr-999", "x")


def test_archive_unarchive_and_delete_forever_only_when_archived(s):
    r = s.requests.ask("personal", "acme", "a", s.tasks)
    assert s.requests.delete_forever(r.id) is False   # never on a live row
    assert s.requests.get(r.id) is not None
    assert s.requests.archive(r.id).archived is True
    assert s.requests.list("acme") == [] and [x.id for x in s.requests.list("acme", include_archived=True)] == [r.id]
    assert s.requests.unarchive(r.id).archived is False
    s.requests.archive(r.id)
    assert s.requests.delete_forever(r.id) is True and s.requests.get(r.id) is None
    text = s.audit_text()
    for ev in ("loka_request_archived", "loka_request_unarchived", "loka_request_deleted_forever"):
        assert ev in text, ev


# ---- the hook the orchestrator calls ----

class Notes:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, text: str, title: str = "Jarvis") -> None:
        self.sent.append((title, text))


def test_deliver_for_task_hands_over_the_plan_deliverable_and_notifies_once(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "write the report", s.tasks)
    s.tasks.set_state(r.task_id, "PLANNED")
    running = s.tasks.set_state(r.task_id, "RUNNING")
    assert deliver_for_task(s.store.conn, s.home, running, None, s.audit).state == "running"
    task = s.finish(r.task_id)
    notes = Notes()
    done = deliver_for_task(s.store.conn, s.home, task, None, s.audit, notes)
    assert done.state == "done" and done.result == "The answer is 42."   # first paragraph of the deliverable
    assert done.deliverable.endswith(f"{task.id}-report.md")
    assert notes.sent == [("Jarvis", "Narada: globex finished the request from acme: The answer is 42.")]
    # a task that answers no request is left alone
    plain = s.tasks.create("plain", workspace="globex")
    assert deliver_for_task(s.store.conn, s.home, s.finish(plain.id), "x", s.audit, notes) is None
    assert len(notes.sent) == 1


def test_deliver_for_task_never_raises(s):
    s.ally("acme", "globex")
    r = s.requests.ask("acme", "globex", "a", s.tasks)
    task = s.finish(r.task_id, body=None)   # the plan names a deliverable that was never written

    class Broken:
        def send(self, text, title="Jarvis"):
            raise RuntimeError("telegram down")

    done = deliver_for_task(s.store.conn, s.home, task, "Done anyway.", s.audit, Broken())
    assert done.state == "done" and done.deliverable is None
    assert "loka_request_notify_failed" in s.audit_text()
    # a broken connection: the hook reports instead of raising
    s.store.conn.close()
    assert deliver_for_task(s.store.conn, s.home, task, None, s.audit) is None
    assert "loka_request_delivery_failed" in s.audit_text()
    s.store = Store(s.home / "data" / "jarvis.db")   # so the fixture can close something


# ---- CLI and chat ----

def test_cli_ask_requests_archive(isolated):
    out = io.StringIO()
    assert main(["workspace", "new", "acme", "--name", "Acme Ltd"], out=io.StringIO()) == 0
    assert main(["workspace", "new", "globex", "--name", "Globex"], out=io.StringIO()) == 0
    assert main(["workspace", "ask", "acme", "globex", "draft the brief"], out=out) == 1
    assert "acme may not ask globex" in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "ask", "personal", "globex", "draft", "the", "brief"], out=out) == 0
    text = out.getvalue()
    assert "Request lr-001: personal asked globex: draft the brief" in text and "jarvis task run t-001" in text
    out = io.StringIO()
    assert main(["workspace", "requests", "globex"], out=out) == 0
    assert "lr-001 [requested] personal -> globex: draft the brief (task t-001)" in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "requests", "acme"], out=out) == 0 and "No requests for acme" in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "request-archive", "lr-001"], out=out) == 0 and "Archived request lr-001" in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "requests"], out=out) == 0 and "lr-001" not in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "requests", "--all"], out=out) == 0 and "lr-001 [requested] (archived)" in out.getvalue()
    out = io.StringIO()
    assert main(["workspace", "request-unarchive", "lr-001"], out=out) == 0 and "Reopened request lr-001" in out.getvalue()
    assert main(["workspace", "request-archive", "lr-999"], out=out) == 1
    assert main(["workspace", "ask", "personal"], out=out) == 2
    audit = (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "loka_request_made" in audit and "loka_request_archived" in audit


def test_chat_ask_and_requests_use_the_session_workspace(isolated):
    main(["workspace", "new", "acme", "--name", "Acme"], out=io.StringIO())
    main(["workspace", "new", "globex", "--name", "Globex"], out=io.StringIO())
    out = io.StringIO()
    inp = io.StringIO("/ask globex write the brief\n/requests\n/workspace acme\n/ask globex more\n/requests\n/ask\n/exit\n")
    assert main(["chat", "--provider", "fake"], out=out, inp=inp) == 0
    text = out.getvalue()
    assert "Request lr-001: personal asked globex: write the brief" in text and "jarvis task run t-001" in text
    assert "lr-001 [requested] personal -> globex" in text
    assert "acme may not ask globex: add it to allies" in text
    assert "No requests for acme" in text
    assert "Usage: /ask <workspace> <goal>" in text
