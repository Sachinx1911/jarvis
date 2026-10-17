"""Astra discipline (jarvis/control/astra.py, PLAN.md 27.4a): one in flight, withdrawn grants,
samhara, and the Brahmastra rules (one target, released once per approval)."""

import json
from dataclasses import replace

import pytest

from jarvis.control.approvals import ApprovalGate
from jarvis.control.astra import (AstraStore, declare_samhara, enforce_samhara, is_irreversible, single_target,
                                  tool_samhara)
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolSpec
from jarvis.tools.registry import Tool, ToolRegistry

OBJ = {"type": "object", "properties": {"path": {"type": "string"}, "to": {"type": "string"}, "q": {"type": "string"},
                                        "paths": {"type": "array", "items": {"type": "string"}}}, "required": []}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class Approver:
    def __init__(self, answer=True):
        self.answer = answer
        self.asked = []

    def __call__(self, req):
        self.asked.append(req)
        return self.answer


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "jarvis.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    yield store, audit, Clock(), tmp_path
    store.close()


def _audit(tmp):
    p = tmp / "audit.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _events(tmp, name):
    return [e for e in _audit(tmp) if e["event"] == name]


# ---- rule (a): one in flight at a time, across lokas ----

def test_inflight_exclusive_across_lokas(env):
    store, audit, clock, tmp = env
    a = AstraStore(store.conn, audit, clock, stale_minutes=30)
    slot, why = a.acquire("gmail_send", "acme", "task-1")
    assert slot and why is None
    other, why = a.acquire("delete_file", "personal", "chat-9")  # another loka, same world
    assert other is None and "another irreversible action is in flight" in why and "gmail_send in acme" in why
    assert _events(tmp, "astra_refused_inflight")[0]["holder"] == "gmail_send"
    a.release(slot, ok=True)
    assert a.live() is None
    slot2, why = a.acquire("delete_file", "personal", "chat-9")
    assert slot2 and why is None


def test_stale_slot_is_taken_over_with_audit(env):
    store, audit, clock, tmp = env
    a = AstraStore(store.conn, audit, clock, stale_minutes=10)
    slot, _ = a.acquire("gmail_send", "acme", "task-1")
    clock.t += 9 * 60
    assert a.acquire("delete_file", "acme", "t2")[0] is None  # not stale yet
    clock.t += 2 * 60
    slot2, why = a.acquire("delete_file", "acme", "t2")
    assert slot2 and why is None
    take = _events(tmp, "astra_stale_takeover")
    assert len(take) == 1 and take[0]["held_by"] == "gmail_send" and take[0]["taken_by"] == "delete_file"
    row = store.conn.execute("SELECT state FROM astra_inflight WHERE id=?", (slot,)).fetchone()
    assert row[0] == "taken_over"


# ---- Brahmastra: released once per approval ----

def test_release_once_consumes_the_approval(env):
    store, audit, clock, tmp = env
    a = AstraStore(store.conn, audit, clock)
    assert a.release_once(7, "gmail_send") is True
    assert a.release_once(7, "gmail_send") is False
    assert a.release_once(None, "gmail_send") is False
    assert _events(tmp, "astra_approval_reused")[0]["approval_id"] == 7


# ---- Brahmastra: one exact target ----

@pytest.mark.parametrize("args,bad", [
    ({"path": "notes/a.md"}, None),
    ({"to": "one@example.com", "subject": "hi *"}, None),       # a star in free text is fine
    ({"paths": ["a.md"]}, None),
    ({"paths": ["a.md", "b.md"]}, "2 targets"),
    ({"path": "notes/*.md"}, "wildcard"),
    ({"path": "all"}, "'all'"),
    ({"to": "a@example.com, b@example.com"}, "more than one recipient"),
    ({"to": "a@example.com; x"}, "more than one recipient"),
    ({"id": "*"}, "'*'"),
])
def test_single_target(args, bad):
    got = single_target(args)
    assert (got is None) if bad is None else (bad in got)


# ---- rule (c): samhara ----

def _tool(name, tier, verify=None, samhara=""):
    return Tool(ToolSpec(name, "x", OBJ), tier, lambda a: "done", verify=verify, samhara=samhara)


def test_tool_samhara_and_irreversible():
    ok = lambda a: (True, "fine")
    assert tool_samhara(_tool("w", "T2", ok)) == "verify"                       # undeclared + verifier
    assert tool_samhara(_tool("w", "T2")) == "none"                             # undeclared, no verifier
    assert tool_samhara(_tool("w", "T2", ok, "none")) == "none"                 # declared none wins
    assert tool_samhara(_tool("w", "T2", None, "verify")) == "none"             # "verify" needs a verifier
    assert tool_samhara(_tool("w", "T2", None, "undo:move_file")) == "undo:move_file"
    assert tool_samhara(_tool("w", "T2", None, "undo:")) == "none"
    assert is_irreversible(_tool("s", "T3", ok, "none")) and not is_irreversible(_tool("s", "T3", ok))
    assert not is_irreversible(_tool("s", "T2", None, "none"))  # a T2 is raised first (enforce_samhara)


def test_declare_and_enforce_samhara(env):
    store, audit, clock, tmp = env
    reg = ToolRegistry(store, audit)
    reg.register(_tool("overwrite_file", "T2", lambda a: (True, "")))
    reg.register(_tool("move_file", "T2", lambda a: (True, "")))
    reg.register(_tool("gmail_send", "T3", lambda a: (True, "")))
    reg.register(_tool("open_url", "T2"))
    reg.register(_tool("mystery_t2", "T2"))               # unknown T2 with no verifier
    reg.register(_tool("read_file", "T0"))
    reg.register(_tool("kept", "T2", None, "undo:kept_back"))  # already declared: kept
    done = declare_samhara(reg)
    assert set(done) == {"overwrite_file", "move_file", "gmail_send", "open_url"}
    assert reg.get("move_file").samhara == "undo:move_file" and reg.get("kept").samhara == "undo:kept_back"
    raised = enforce_samhara(reg, audit)
    assert set(raised) == {"open_url", "mystery_t2"}
    assert reg.get("open_url").tier == "T3" and is_irreversible(reg.get("open_url"))
    assert reg.get("mystery_t2").tier == "T3"
    assert reg.get("overwrite_file").tier == "T2" and reg.get("read_file").tier == "T0"
    assert reg.get("gmail_send").tier == "T3" and is_irreversible(reg.get("gmail_send"))
    missing = _events(tmp, "samhara_missing")
    assert {e["tool"] for e in missing} == {"open_url", "mystery_t2"} and missing[0]["now"] == "T3"
    assert enforce_samhara(reg, audit) == []  # once


# ---- through the registry ----

def _reg(env, approver, clock=None, workspace="acme"):
    store, audit, clk, _ = env
    gate = ApprovalGate(store, audit, approver, clock=clock or clk)
    reg = ToolRegistry(store, audit, gate, workspace=workspace, astra_stale_minutes=30)
    return reg


def test_second_t3_refused_while_one_is_in_flight(env):
    store, audit, clock, tmp = env
    ap = Approver(True)
    reg = _reg(env, ap)
    other = _reg(env, ap, workspace="personal")
    held = {}

    def slow(a):  # while this T3 runs, another loka tries one
        held["res"] = other.execute(ToolCall("x", "delete_file", {"path": "b.md"}))
        return "sent"

    reg.register(Tool(ToolSpec("gmail_send", "x", OBJ), "T3", slow, verify=lambda a: (True, "in sent"), samhara="none"))
    other.register(Tool(ToolSpec("delete_file", "x", OBJ), "T3", lambda a: "gone", verify=lambda a: (True, "")))
    out = reg.execute(ToolCall("1", "gmail_send", {"to": "a@example.com"}), task_id="t1")
    assert not out.is_error
    assert held["res"].is_error and "another irreversible action is in flight" in held["res"].content
    assert "gmail_send in acme" in held["res"].content
    refused = [e for e in _events(tmp, "tool_run") if e["decision"] == "refused_inflight"]
    assert len(refused) == 1 and refused[0]["tool"] == "delete_file"
    # released after verify: the user can retry
    assert not other.execute(ToolCall("2", "delete_file", {"path": "b.md"})).is_error


def test_slot_released_when_the_tool_fails(env):
    store, audit, clock, tmp = env
    reg = _reg(env, Approver(True))

    def boom(a):
        raise RuntimeError("smtp down")

    reg.register(Tool(ToolSpec("gmail_send", "x", OBJ), "T3", boom, samhara="none"))
    assert reg.execute(ToolCall("1", "gmail_send", {"to": "a@example.com"})).is_error
    assert reg._astra().live() is None


def test_wildcard_and_bulk_refused_for_irreversible(env):
    store, audit, clock, tmp = env
    ap = Approver(True)
    reg = _reg(env, ap)
    reg.register(Tool(ToolSpec("delete_file", "x", OBJ), "T3", lambda a: "gone", samhara="none"))
    reg.register(Tool(ToolSpec("move_file", "x", OBJ), "T3", lambda a: "moved", verify=lambda a: (True, "")))
    out = reg.execute(ToolCall("1", "delete_file", {"path": "notes/*.md"}))
    assert out.is_error and "wildcard" in out.content and ap.asked == []  # refused before anyone is asked
    out = reg.execute(ToolCall("2", "delete_file", {"paths": ["a.md", "b.md"]}))
    assert out.is_error and "2 targets" in out.content
    assert len(_events(tmp, "astra_refused_target")) == 2
    # a T3 with a withdrawal path is not the Brahmastra: the target rule does not apply
    assert not reg.execute(ToolCall("3", "move_file", {"path": "notes/*.md"})).is_error


def test_approval_consumed_once(env):
    """Each run of the Brahmastra spends the approval it was given; a gate that hands out no
    fresh approval row cannot release it again."""
    store, audit, clock, tmp = env
    ap = Approver(True)
    reg = _reg(env, ap)
    reg.register(Tool(ToolSpec("gmail_send", "x", OBJ), "T3", lambda a: "sent", samhara="none"))
    assert not reg.execute(ToolCall("1", "gmail_send", {"to": "a@example.com"})).is_error
    first = reg.gate.last_approval_id
    assert not reg.execute(ToolCall("2", "gmail_send", {"to": "a@example.com"})).is_error  # a new approval
    assert reg.gate.last_approval_id != first
    assert store.conn.execute("SELECT COUNT(*) FROM astra_releases").fetchone()[0] == 2
    # Replay: the gate records nothing new (as if its decision were reused), so the release is refused.
    reg.gate._record = lambda *a, **k: None
    out = reg.execute(ToolCall("3", "gmail_send", {"to": "a@example.com"}))
    assert out.is_error and "already used once" in out.content
    assert reg._astra().live() is None
    assert _events(tmp, "tool_run")[-1]["decision"] == "refused_reused_approval"


def test_denied_t3_never_touches_the_slot(env):
    store, audit, clock, tmp = env
    reg = _reg(env, Approver(False))
    reg.register(Tool(ToolSpec("gmail_send", "x", OBJ), "T3", lambda a: "sent", samhara="none"))
    assert reg.execute(ToolCall("1", "gmail_send", {"to": "a@example.com"})).is_error
    assert reg._astra().live() is None
    assert store.conn.execute("SELECT COUNT(*) FROM astra_inflight").fetchone()[0] == 0


# ---- rule (b): a failed verification withdraws the grant ----

def test_failed_verify_withdraws_grants_until_regranted(env):
    store, audit, clock, tmp = env
    ap = Approver(True)
    reg = _reg(env, ap, workspace="acme")
    reg.register(Tool(ToolSpec("overwrite_file", "x", OBJ), "T2", lambda a: "done",
                      verify=lambda a: (False, "file unchanged")))
    gs = reg.gate.grants
    g_any = gs.create("overwrite_file", "T2", {"q": {"equals": "x"}}, 7, 5)                   # every loka
    g_acme = gs.create("overwrite_file", "T2", {"q": {"equals": "y"}}, 7, 5, workspace="acme")
    g_other = gs.create("overwrite_file", "T2", {"q": {"equals": "z"}}, 7, 5, workspace="beta")
    g_tool = gs.create("move_file", "T2", {"q": {"equals": "x"}}, 7, 5)
    out = reg.execute(ToolCall("1", "overwrite_file", {"q": "x"}), task_id="t1")
    assert not out.is_error and "[NOT verified: file unchanged]" in out.content
    assert ap.asked == []  # the grant answered for Sachin; then the deed could not be verified
    assert gs.get(g_any.id).revoked and gs.get(g_acme.id).revoked
    assert not gs.get(g_other.id).revoked and not gs.get(g_tool.id).revoked  # other loka, other tool
    w = _events(tmp, "grant_withdrawn")
    assert len(w) == 1 and w[0]["tool"] == "overwrite_file" and w[0]["workspace"] == "acme"
    assert set(w[0]["grants"]) == {g_any.id, g_acme.id} and "file unchanged" in w[0]["reason"]
    marks = reg._astra().needs_regrant()
    assert len(marks) == 1 and marks[0]["tool"] == "overwrite_file" and marks[0]["workspace"] == "acme"
    assert reg._astra().needs_regrant("beta") == []
    # the next use asks Sachin (no grant answers any more), then a fresh grant lifts the mark
    reg.execute(ToolCall("2", "overwrite_file", {"q": "x"}))
    assert len(ap.asked) == 1
    gs.create("overwrite_file", "T2", {"q": {"equals": "x"}}, 7, 5, workspace="acme")
    assert reg._astra().needs_regrant() == []


def test_t1_verify_failure_does_not_withdraw(env):
    store, audit, clock, tmp = env
    reg = _reg(env, Approver(True))
    reg.register(Tool(ToolSpec("write_file", "x", OBJ), "T1", lambda a: "done", verify=lambda a: (False, "nope")))
    gs = reg.gate.grants
    g = gs.create("write_file", "T1", {"q": {"equals": "x"}}, 7, 5)
    reg.execute(ToolCall("1", "write_file", {"q": "x"}))
    assert not gs.get(g.id).revoked and _events(tmp, "grant_withdrawn") == []


def test_loka_bound_grant_answers_only_in_its_loka(env):
    store, audit, clock, tmp = env
    gs = ApprovalGate(store, audit, None, clock=clock).grants
    gs.create("overwrite_file", "T2", {"q": {"equals": "x"}}, 7, 5, workspace="acme")
    assert gs.find("overwrite_file", "T2", {"q": "x"}, "acme")
    assert gs.find("overwrite_file", "T2", {"q": "x"}, "beta") is None
    assert gs.find("overwrite_file", "T2", {"q": "x"}) is None
    gs.create("overwrite_file", "T2", {"q": {"equals": "x"}}, 7, 5)  # loka-less: everywhere
    assert gs.find("overwrite_file", "T2", {"q": "x"}, "beta")


def test_grants_table_from_before_lokas_is_upgraded(env):
    store, audit, clock, tmp = env
    store.conn.executescript("""
    CREATE TABLE standing_grants (id TEXT PRIMARY KEY, tool TEXT NOT NULL, tier TEXT NOT NULL,
        constraints TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, max_uses INTEGER NOT NULL,
        uses INTEGER NOT NULL DEFAULT 0, revoked INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL, last_used REAL);
    INSERT INTO standing_grants VALUES ('g-old', 'overwrite_file', 'T2', '{"q": {"equals": "x"}}', 1, 2e9, 5, 0, 0,
        '', 'cli', NULL);
    """)
    gs = ApprovalGate(store, audit, None, clock=clock).grants
    assert gs.get("g-old").workspace == "" and gs.get("g-old").public(clock())["workspace"] == ""
    assert gs.find("overwrite_file", "T2", {"q": "x"}, "any-loka").id == "g-old"
