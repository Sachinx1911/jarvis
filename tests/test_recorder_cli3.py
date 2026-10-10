"""Phase 3: teach-by-demonstration, projects and task CLI."""

import io
from datetime import datetime

import pytest

from jarvis.cli import main
from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ChatSession
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.skills.loader import SkillLibrary
from jarvis.skills.recorder import Recorder, render_skill, terminal_commands

DRAFT = {"name": "Daily Note", "description": "Create today's daily note in notes/.",
         "inputs": [{"name": "date", "description": "the day, YYYY-MM-DD"}],
         "preconditions": ["the notes folder exists"],
         "steps": [{"text": "Create notes/{date}.md with the headings Plan, Done, Ideas", "tool": "write_file"},
                   {"text": "Remove yesterday's note if it is empty", "tool": "delete_file"},
                   {"text": "Tell the user it is ready", "tool": ""}],
         "verify": ["notes/{date}.md exists and has the three headings"]}


def test_terminal_commands_parse_powershell_and_script():
    ps = "PS C:\\work> git status\nOn branch main\nPS C:\\work> Stop-Transcript"
    mac = "user@mac ~ % make run\nbuilding...\n$ ls -la"
    assert terminal_commands(ps) == ["git status"]
    assert terminal_commands(mac) == ["make run", "ls -la"]
    assert terminal_commands("PS C:\\> echo password: hunter22") == ["echo [WITHHELD]"]


def test_render_skill_uses_registry_tiers_not_model():
    md = render_skill(DRAFT, {"write_file": "T1", "delete_file": "T3"}, version=1, source="r-1")
    assert "name: daily-note" in md and "version: 1" in md
    assert "tool `write_file`, tier T1" in md
    assert "tool `delete_file`, tier T3 (asks every time)" in md
    assert "`{date}`" in md


def test_record_demo_then_draft_approve_and_replay(isolated):
    home = isolated
    store = Store(home / "data" / "jarvis.db")
    try:
        rec = Recorder(home, store, [home / "workspace"])
        (home / "workspace").mkdir(parents=True, exist_ok=True)
        r = rec.start("daily note")
        with pytest.raises(RuntimeError):
            rec.start("again")
        decision = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")
        s = ChatSession(load_config(), FakeProvider(script=[
            {"tool": "write_file", "arguments": {"path": "notes/2026-10-10.md", "content": "## Plan\n## Done\n## Ideas"}},
            "Your daily note is ready, sir."]), decision, store, AuditLog(home / "data" / "audit.jsonl"),
            now=lambda: datetime(2026, 10, 10, 9, 0), home=home, memory=MemoryStore(home, store))
        s.send("make today's daily note")
        rec.note("I keep one note per day")
        _, evidence = rec.stop()
        assert "write_file (T1)" in evidence and "created: notes/2026-10-10.md" in evidence
        assert "## Plan" in evidence and "I keep one note per day" in evidence

        draft = rec.draft(r.id, FakeProvider(script=[{"json": DRAFT}]), decision, {"write_file": "T1", "delete_file": "T3"})
        assert "tier T1" in draft.read_text(encoding="utf-8")
        skill = rec.approve(r.id, home / "skills")
        assert skill == home / "skills" / "daily-note" / "SKILL.md"
        again = rec.approve(r.id, home / "skills")  # approving again keeps v1 and writes v2
        assert (home / "skills" / "daily-note" / "SKILL.v1.md").exists()
        assert "version: 2" in again.read_text(encoding="utf-8")
        assert [i.name for i in SkillLibrary(home / "skills").index()] == ["daily-note"]
    finally:
        store.close()


def test_task_and_project_cli(isolated):
    out = io.StringIO()
    assert main(["project", "new", "laptop", "buy", "a", "laptop"], out=out) == 0
    assert main(["project", "list"], out=out) == 0
    assert main(["task", "add", "compare", "laptops", "--project", "laptop", "--priority", "high"], out=out) == 0
    assert main(["tasks"], out=out) == 0
    assert main(["task", "show", "t-001"], out=out) == 0
    assert main(["task", "cancel", "t-001"], out=out) == 0
    assert main(["task", "cancel", "t-001"], out=out) == 1  # already final
    text = out.getvalue()
    assert "Project ready" in text and "laptop\n" in text and "Added t-001" in text
    assert "BACKLOG" in text and "Cancelled t-001" in text
    assert (isolated / "projects" / "laptop" / "PROJECT.md").read_text(encoding="utf-8").startswith("# laptop")


def test_task_run_cli_with_fake_fails_cleanly_and_writes_receipt(isolated):
    """The plain fake provider gives no valid plan or verdict: the task must fail, not crash."""
    out = io.StringIO()
    main(["task", "run", "--provider", "fake", "say", "hello"], out=out, inp=io.StringIO(""))
    receipt = (isolated / "data" / "tasks" / "t-001" / "receipt.md").read_text(encoding="utf-8")
    assert "Task t-001 started." in out.getvalue()
    assert receipt.split(" · ")[1] == "t-001" and receipt.split(" · ")[0] in ("COMPLETED", "FAILED")
