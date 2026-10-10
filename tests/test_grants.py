"""Standing approvals (jarvis/control/grants.py) and their use in the approval gate."""

import io
import json

import pytest

from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.control.grants import GrantError, GrantStore, _glob_match
from jarvis.db import Store
from jarvis.providers.base import ToolCall
from jarvis.tools.registry import Tool, ToolRegistry
from jarvis.providers.base import ToolSpec


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "notes").mkdir(parents=True)
    store = Store(tmp_path / "data" / "jarvis.db")
    clock = Clock()
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    yield store, [ws], clock, audit, tmp_path
    store.close()


def _grants(env):
    store, roots, clock, _, _ = env
    return GrantStore(store.conn, roots, clock)


def _note_grant(gs, **kw):
    rules = {"path": {"glob": "notes/*.md"}, "content": {"max_chars": 100}}
    return gs.create("write_file", "T1", rules, kw.pop("days", 7), kw.pop("max_uses", 3), **kw)


def test_glob_segments():
    assert _glob_match("/w/notes/*.md", "/w/notes/a.md")
    assert not _glob_match("/w/notes/*.md", "/w/notes/sub/a.md")
    assert _glob_match("/w/notes/**/*.md", "/w/notes/sub/deep/a.md")
    assert not _glob_match("/w/notes/*.md", "/w/other/a.md")


def test_exact_match_needed(env):
    gs = _grants(env)
    g = _note_grant(gs)
    assert gs.find("write_file", "T1", {"path": "notes/day.md", "content": "hi"}).id == g.id
    assert gs.find("write_file", "T1", {"path": "notes/day.txt", "content": "hi"}) is None      # glob
    assert gs.find("write_file", "T1", {"path": "notes/day.md", "content": "x" * 101}) is None  # size
    assert gs.find("write_file", "T1", {"path": "notes/day.md", "content": "hi", "extra": "1"}) is None  # no rule
    assert gs.find("overwrite_file", "T1", {"path": "notes/day.md", "content": "hi"}) is None  # other tool
    assert gs.find("write_file", "T1", {"path": "notes/../../x.md", "content": "hi"}) is None  # escapes


def test_expiry_and_max_uses(env):
    gs = _grants(env)
    clock = env[2]
    g = _note_grant(gs, max_uses=2)
    args = {"path": "notes/a.md", "content": "x"}
    assert gs.consume(g, None, args) and gs.consume(g, None, args)
    assert not gs.consume(g, None, args)              # used up
    assert gs.find("write_file", "T1", args) is None
    assert gs.get(g.id).public(clock()).get("status") == "used up"
    g2 = _note_grant(gs, days=1)
    clock.t += 86400 + 1
    assert gs.find("write_file", "T1", args) is None  # expired
    assert gs.get(g2.id).status(clock()) == "expired"
    assert len(gs.uses(g.id)) == 2


def test_revoke_stops_it(env):
    gs = _grants(env)
    g = _note_grant(gs)
    gs.revoke(g.id)
    assert gs.find("write_file", "T1", {"path": "notes/a.md", "content": "x"}) is None
    with pytest.raises(KeyError):
        gs.revoke("g-00000000")


@pytest.mark.parametrize("tier", ["T3", "T4", "T0"])
def test_never_t3_t4(env, tier):
    gs = _grants(env)
    with pytest.raises(GrantError):
        gs.create("delete_file", tier, {"path": {"glob": "notes/*"}}, 7, 3)


@pytest.mark.parametrize("rules,needle", [
    ({"path": {"any": True}}, "exact rule"),
    ({"path": {"glob": "../*"}}, ".."),
    ({"path": {"glob": "C:/Windows/*"}}, "not inside"),
    ({"path": {"glob": ".ssh/*"}}, "secret"),
    ({"url": {"equals": "https://x.com"}}, "domain"),
    ({"url": {"domain": "https://x.com/"}}, "plain site"),
    ({"content": {"regex": "."}}, "unknown rule"),
    ({}, "at least one"),
])
def test_bad_rules_refused(env, rules, needle):
    with pytest.raises(GrantError, match=needle):
        _grants(env).create("write_file", "T1", rules, 7, 3)


def test_limits_on_days_uses_and_creator(env):
    gs = _grants(env)
    rules = {"path": {"glob": "notes/*.md"}}
    for days, uses in [(91, 3), (0, 3), (7, 0), (7, 1001)]:
        with pytest.raises(GrantError):
            gs.create("write_file", "T1", rules, days, uses)
    with pytest.raises(GrantError):
        gs.create("write_file", "T1", rules, 7, 3, created_by="model")


def test_domain_rule(env):
    gs = _grants(env)
    gs.create("open_url", "T2", {"url": {"domain": "example.com"}}, 7, 5)
    assert gs.find("open_url", "T2", {"url": "https://www.example.com/page"})
    assert gs.find("open_url", "T2", {"url": "https://example.com.evil.net/"}) is None
    assert gs.find("open_url", "T2", {"url": "https://example.com/?q=" + "QUJD" * 20 + "1"}) is None  # exfil
    assert gs.find("open_url", "T2", {"url": "ftp://example.com/"}) is None


# ---- the gate ----

def _gate(env, approver=None):
    store, roots, clock, audit, _ = env
    return ApprovalGate(store, audit, approver, roots=roots, clock=clock)


def test_gate_uses_grant_without_asking_and_audits(env):
    store, _, _, audit, _ = env
    asked = []
    gate = _gate(env, lambda r: asked.append(r) or False)
    g = _note_grant(gate.grants)
    ok, how = gate.check("write_file", "T1", {"path": "notes/a.md", "content": "x"}, tainted=True,
                         task_id="t1", hostile=False)
    assert ok and g.id in how and not asked
    events = [json.loads(l) for l in audit.path.read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "grant_used" and e["grant_id"] == g.id for e in events)
    row = store.conn.execute("SELECT decision FROM approvals ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == f"approved_grant:{g.id}"


def test_gate_unattended_runs_with_grant(env):
    gate = _gate(env, None)  # schedules and triggers: nobody to ask
    _note_grant(gate.grants)
    assert gate.check("write_file", "T1", {"path": "notes/a.md", "content": "x"}, True, None, hostile=False)[0]
    assert not gate.check("write_file", "T1", {"path": "other.md", "content": "x"}, True, None, hostile=False)[0]


def test_gate_never_for_t3_t4_even_with_a_row(env):
    store = env[0]
    gate = _gate(env, None)
    gs = gate.grants
    # A grant row for a T3 tool written behind the store's back still never applies.
    store.conn.execute("""INSERT INTO standing_grants (id, tool, tier, constraints, created, expires, max_uses,
                          created_by) VALUES ('g-deadbeef', 'delete_file', 'T2', ?, 0, 9e12, 9, 'cli')""",
                       (json.dumps({"path": {"glob": str(env[1][0].as_posix()) + "/**"}}),))
    store.conn.commit()
    assert gs.get("g-deadbeef")
    assert not gate.check("delete_file", "T3", {"path": "notes/a.md"}, False, None, hostile=False)[0]
    assert not gate.check("delete_file", "T4", {"path": "notes/a.md"}, False, None, hostile=False)[0]


def test_gate_never_when_hostile_or_unknown_and_tainted(env):
    gate = _gate(env, None)
    _note_grant(gate.grants)
    args = {"path": "notes/a.md", "content": "x"}
    assert not gate.check("write_file", "T1", args, True, None, hostile=True)[0]
    assert not gate.check("write_file", "T1", args, True, None)[0]          # caller did not say: fail closed
    gate2 = _gate(env, None)
    gate2.grants.create("overwrite_file", "T2", {"path": {"glob": "notes/*.md"}, "content": {"any": True}}, 7, 3)
    assert gate2.check("overwrite_file", "T2", args, False, None)[0]        # untainted: fine without the flag


def test_gate_never_when_egress_flags(env):
    gate = _gate(env, None)
    gate.grants.create("open_url", "T2", {"url": {"domain": "example.com"}}, 7, 3)
    args = {"url": "https://example.com/x"}
    assert not gate.check("open_url", "T2", args, True, None, force_reason="link not given by you", hostile=False)[0]
    assert not gate.check("open_url", "T2", args, False, None, notes=("url: link ...; WARNING: x",), hostile=False)[0]
    assert gate.check("open_url", "T2", args, False, None, hostile=False)[0]


def test_registry_path_auto_approves_with_grant(env):
    """Through the registry (which today does not pass hostile): untainted T2 call uses the grant."""
    store, roots, clock, audit, tmp = env
    gate = _gate(env, None)
    gate.grants.create("overwrite_file", "T2", {"path": {"glob": "notes/*.md"}, "content": {"max_chars": 50}}, 7, 1)
    (roots[0] / "notes" / "a.md").write_text("old", encoding="utf-8")
    ran = []
    reg = ToolRegistry(store, audit, gate)
    reg.register(Tool(ToolSpec("overwrite_file", "x", {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}), "T2",
        lambda a: ran.append(a) or "done"))
    assert not reg.execute(ToolCall("1", "overwrite_file", {"path": "notes/a.md", "content": "new"})).is_error
    assert reg.execute(ToolCall("2", "overwrite_file", {"path": "notes/a.md", "content": "new"})).is_error  # 1 use
    assert len(ran) == 1


# ---- CLI ----

def test_cli_grant_list_revoke(isolated):
    from jarvis.cli import main

    (isolated / "workspace" / "notes").mkdir(parents=True, exist_ok=True)
    out = io.StringIO()
    code = main(["approvals", "grant", "write_file", "--rule", "path=glob:notes/*.md", "--rule",
                 "content=max_chars:500", "--days", "3", "--uses", "4", "--note", "daily notes"], out=out,
                inp=io.StringIO())
    assert code == 0, out.getvalue()
    gid = out.getvalue().split("g-", 1)[1][:8]
    out = io.StringIO()
    main(["approvals", "list"], out=out, inp=io.StringIO())
    assert f"g-{gid}" in out.getvalue() and "uses 0/4" in out.getvalue()
    out = io.StringIO()
    assert main(["approvals", "grant", "delete_file", "--rule", "path=glob:notes/*"], out=out, inp=io.StringIO()) == 1
    assert "only for T1 and T2" in out.getvalue()
    out = io.StringIO()
    assert main(["approvals", "revoke", f"g-{gid}"], out=out, inp=io.StringIO()) == 0
    out = io.StringIO()
    main(["approvals", "list"], out=out, inp=io.StringIO())
    assert "No active standing approvals" in out.getvalue()
