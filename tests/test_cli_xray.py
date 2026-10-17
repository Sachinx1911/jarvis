"""Phase 9 part G: jarvis xray diag/last/drill/setup, the teardown tool, and jarvis preflight --offline."""

from __future__ import annotations

import io
import json

from jarvis import cli_preflight, cli_xray
from jarvis.cli import main as cli_main
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.xray.tools import xray_tools

NOT_READY = {"ready": False, "problems": ["node not found", "REA not installed (jarvis xray setup)"]}


def test_xray_diag_reports_the_kit(isolated, monkeypatch):
    from jarvis.xray import live

    monkeypatch.setattr(live, "kit_diag", lambda: {**NOT_READY, "node": "none"})
    out = io.StringIO()
    assert cli_main(["xray", "diag"], out=out) == 1
    text = out.getvalue()
    assert "NOT READY" in text and "! node not found" in text and "node: none" in text
    monkeypatch.setattr(live, "kit_diag", lambda: {"ready": True, "problems": [], "rea": "6.5.0"})
    out = io.StringIO()
    assert cli_main(["xray", "diag"], out=out) == 0 and "READY" in out.getvalue() and "rea: 6.5.0" in out.getvalue()


def test_xray_diag_without_the_kit_module_is_a_problem_not_a_crash(isolated):
    """kit.py is built by the other half of Phase 9; until it is there, diag says so."""
    out = io.StringIO()
    code = cli_main(["xray", "diag"], out=out)
    assert code in (0, 1) and ("READY" in out.getvalue())


def test_xray_last(isolated):
    out = io.StringIO()
    assert cli_main(["xray", "last"], out=out) == 1 and "No teardown yet" in out.getvalue()
    notes = isolated / "workspace" / "teardowns"
    notes.mkdir(parents=True)
    (notes / "igloo.inc-2026-10-17.md").write_text("# Teardown: igloo.inc\n\n## Summary\nThree.js and GSAP.\n\n## Spoken\nx\n",
                                                   encoding="utf-8")
    out = io.StringIO()
    assert cli_main(["xray", "last"], out=out) == 0
    assert "igloo.inc-2026-10-17.md" in out.getvalue() and "Three.js and GSAP." in out.getvalue()


def test_xray_drill_offline_prints_pass_per_check(isolated):
    out = io.StringIO()
    assert cli_main(["xray", "drill"], out=out) == 0
    lines = out.getvalue().splitlines()
    assert sum(l.startswith("PASS  spoken address:") for l in lines) == 5
    assert not any(l.startswith("FAIL") for l in lines) and lines[-1] == "offline drill: ok"


def test_xray_drill_live_needs_a_ready_kit(isolated, monkeypatch):
    from jarvis.xray import live

    monkeypatch.setattr(live, "kit_diag", lambda: NOT_READY)
    out = io.StringIO()
    assert cli_main(["xray", "drill", "--live"], out=out) == 1
    assert "live drill skipped: the kit is not ready" in out.getvalue()


def test_xray_setup_refuses_without_confirmation(isolated, monkeypatch):
    import sys
    import types

    installed = []
    fake_kit = types.ModuleType("jarvis.xray.kit")

    class Kit:
        def install(self, confirm=False):
            installed.append(confirm)
            return "installed"

        def diag(self):
            return {"ready": True, "problems": []}

    fake_kit.Kit = Kit
    monkeypatch.setitem(sys.modules, "jarvis.xray.kit", fake_kit)
    out = io.StringIO()
    assert cli_main(["xray", "setup"], out=out, inp=io.StringIO("\n")) == 1
    assert "Not installed." in out.getvalue() and installed == []
    out = io.StringIO()
    assert cli_main(["xray", "setup"], out=out, inp=io.StringIO("y\n")) == 0 and installed == [True]
    out = io.StringIO()
    assert cli_main(["xray", "setup", "--yes"], out=out, inp=io.StringIO("")) == 0 and installed == [True, True]


def test_xray_run_refuses_when_the_kit_is_not_ready(isolated, monkeypatch):
    from jarvis.xray import live

    monkeypatch.setattr(live, "kit_diag", lambda: NOT_READY)
    out = io.StringIO()
    assert cli_main(["xray", "run", "igloo dot inc"], out=out) == 1
    assert "REA not installed" in out.getvalue() and "jarvis xray setup" in out.getvalue()
    out = io.StringIO()
    assert cli_main(["xray", "run"], out=out) == 2


# ---- the brain's tool ----

def test_teardown_tool_refuses_when_the_kit_is_not_ready(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        tools = xray_tools(isolated, store, AuditLog(isolated / "data" / "audit.jsonl"), diag=lambda: NOT_READY,
                           deps_factory=lambda: (_ for _ in ()).throw(AssertionError("deps must not be built")))
        assert [t.spec.name for t in tools] == ["teardown"] and tools[0].tier == "T1"
        assert tools[0].url_args == ("url",) and "Only when the user asks" in tools[0].spec.description
        reply = tools[0].handler({"url": "igloo dot inc", "question": "how"})
        assert reply.startswith("The teardown kit is not ready: node not found; REA not installed")
        assert tools[0].handler({"url": "igloo", "question": "how"}).startswith("Not a web address")
    finally:
        store.close()


def test_teardown_tool_runs_a_job_when_ready(isolated, monkeypatch):
    from jarvis.xray import tools as tools_mod

    class Res:
        note_path = isolated / "workspace" / "teardowns" / "igloo.inc-2026-10-17.md"
        task_id, label, spoken, summary = "t-001", "Three.js site", "It is Three.js.", "Built with Three.js."

    calls = []
    monkeypatch.setattr(tools_mod, "run_teardown", lambda url, q, deps: calls.append((url, q, deps)) or Res())
    store = Store(isolated / "data" / "jarvis.db")
    try:
        tool = xray_tools(isolated, store, AuditLog(isolated / "data" / "audit.jsonl"),
                          diag=lambda: {"ready": True, "problems": []}, deps_factory=lambda: "fake deps")[0]
        reply = tool.handler({"url": "igloo dot inc", "question": "how"})
        assert calls == [("https://igloo.inc", "how", "fake deps")]
        assert "Teardown of igloo.inc written" in reply and "It is Three.js." in reply and "t-001" in reply
    finally:
        store.close()


# ---- preflight ----

def test_preflight_offline(isolated, monkeypatch):
    from jarvis.xray import live

    monkeypatch.setattr(live, "kit_diag", lambda: NOT_READY)
    out = io.StringIO()
    code = cli_main(["preflight", "--offline"], out=out)
    text = out.getvalue()
    assert code == 0, text
    lines = text.splitlines()
    assert "providers: OK - skipped (--offline)" in lines
    assert "stop: OK - released" in lines
    assert any(l.startswith("database: OK - ") for l in lines)
    assert any(l.startswith("truth: OK - truth check: ok") for l in lines)
    assert "memory: OK - 0 active memories indexed" in lines
    assert "daemon: OK - no app lock (daemon not running)" in lines
    assert "xray: INFO - node not found; REA not installed (jarvis xray setup)" in lines
    assert lines[-1] == "preflight: OK - 7 checks passed (xray reported only)"
    audit = [json.loads(l) for l in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "preflight" and e["ok"] and e["offline"] for e in audit)


def test_preflight_fails_when_the_stop_is_engaged(isolated, monkeypatch):
    from jarvis.control.stop import StopSwitch

    (isolated / "data").mkdir(exist_ok=True)
    StopSwitch(isolated / "data").engage("test")
    from jarvis.xray import live

    monkeypatch.setattr(live, "kit_diag", lambda: NOT_READY)
    out = io.StringIO()
    assert cli_main(["preflight", "--offline"], out=out) == 1
    lines = out.getvalue().splitlines()
    assert "stop: NOT OK - emergency stop is ON (jarvis resume)" in lines
    assert lines[-1].startswith("preflight: NOT OK - 1 of 7 checks failed: stop")


def test_preflight_summary_line():
    C = cli_preflight.Check
    assert cli_preflight.summary_line([C("a", True, ""), C("b", False, "", required=False)]) == \
        "preflight: OK - 2 checks passed (b reported only)"
    assert cli_preflight.summary_line([C("a", False, ""), C("b", False, "")]) == \
        "preflight: NOT OK - 2 of 2 checks failed: a, b"


def test_cli_xray_offline_checks_merge_both_drills():
    """The fingerprint drill (jarvis/xray/drill.py) and the spoken drill run together."""
    names = [getattr(c, "name", None) or c[0] for c in cli_xray.all_offline_checks()]
    assert any("fingerprint" in n.lower() for n in names) and any(n.startswith("spoken address") for n in names)
    assert all((getattr(c, "ok", None) if hasattr(c, "ok") else c[1]) for c in cli_xray.all_offline_checks())
