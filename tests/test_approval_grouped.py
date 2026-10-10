"""Grouped low-risk approvals: a second new-file write in a row in the same folder offers a
session grant for that folder; it never leaves the gate (one chat or task)."""

import pytest

from jarvis.control.approvals import SESSION_GRANT_MAX_S, ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.db import Store


class Clock:
    t = 5_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "notes").mkdir(parents=True)
    (ws / "other").mkdir()
    store = Store(tmp_path / "data" / "jarvis.db")
    asked = []
    answers = []

    def approver(req):
        asked.append(req)
        return answers.pop(0) if answers else True

    clock = Clock()
    gate = ApprovalGate(store, AuditLog(tmp_path / "audit.jsonl"), approver, roots=[ws], clock=clock)
    yield gate, asked, answers, clock
    store.close()


def _w(gate, name, task="t-1", **kw):
    return gate.check("write_file", "T1", {"path": name, "content": "x"}, tainted=True, task_id=task, **kw)


def test_ask_once_for_the_folder(setup):
    gate, asked, _, _ = setup
    assert _w(gate, "notes/a.md")[0] and asked[-1].scope == ""         # first: plain question
    assert asked[-1].preview.startswith("Create new file: [[notes/a.md]]")
    assert _w(gate, "notes/b.md")[0]
    assert "workspace/notes" in asked[-1].scope                         # second: offers the folder
    n = len(asked)
    ok, how = _w(gate, "notes/c.md")
    assert ok and "earlier in this session" in how and len(asked) == n  # third: no question
    assert _w(gate, "other/d.md")[0] and len(asked) == n + 1            # other folder still asks
    assert _w(gate, "notes/sub/e.md")[0] and len(asked) == n + 2        # subfolder is not covered


def test_denied_or_interrupted_runs_do_not_group(setup):
    gate, asked, answers, _ = setup
    _w(gate, "notes/a.md")
    _w(gate, "other/x.md")                       # not in a row
    _w(gate, "notes/b.md")
    assert asked[-1].scope == ""
    answers.append(False)
    _w(gate, "notes/c.md")                       # offered, but denied: no grant
    assert asked[-1].scope
    _w(gate, "notes/d.md")
    assert asked[-1].scope == ""                 # chain was reset by the deny


def test_scoped_to_task_expiry_and_end(setup):
    gate, asked, _, clock = setup
    _w(gate, "notes/a.md")
    _w(gate, "notes/b.md")                       # grant for task t-1
    n = len(asked)
    _w(gate, "notes/c.md", task="t-2")
    assert len(asked) == n + 1                   # another task: asks
    _w(gate, "notes/d.md")
    assert len(asked) == n + 1                   # same task: grant
    clock.t += SESSION_GRANT_MAX_S + 1
    _w(gate, "notes/e.md")
    assert len(asked) == n + 2                   # expired
    _w(gate, "notes/f.md")                       # offered again and granted
    gate.end_session()
    _w(gate, "notes/g.md")
    assert len(asked) == n + 4                   # ended with the session


def test_never_hostile_flagged_or_other_tools(setup):
    gate, asked, _, _ = setup
    _w(gate, "notes/a.md")
    _w(gate, "notes/b.md")
    n = len(asked)
    _w(gate, "notes/c.md", hostile=True)
    assert len(asked) == n + 1                   # hostile session: asks again
    _w(gate, "notes/d.md", force_reason="egress")
    assert len(asked) == n + 2
    gate.check("overwrite_file", "T2", {"path": "notes/a.md", "content": "y"}, True, "t-1")
    assert len(asked) == n + 3                   # overwrite is never grouped
