"""Connector registry entries, default tiers, health checks, EventKit guard and the Phase 5 CLI.

Apple Notes has its own file (test_applenotes.py)."""

import argparse
import io
import shutil
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from jarvis import cli_connectors
from jarvis.connectors import eventkit
from jarvis.connectors.applenotes import FakeNotesRunner
from jarvis.connectors.config import get_tz, load_connectors_config
from jarvis.connectors.google import auth
from jarvis.connectors.google.fake import FakeGoogleClient
from jarvis.connectors.registry import (ConnectorDeps, _with_declared_tier, apply_connector_registry,
                                        connector_health, connector_tools, declared, doc_library,
                                        write_connector_registry)
from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolSpec
from jarvis.tools.registry import Tool, ToolRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "docs"
NOW = datetime(2026, 10, 10, 15, 0, tzinfo=get_tz("Asia/Kolkata"))


@pytest.fixture
def deps(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    cfg = load_connectors_config()
    d = ConnectorDeps(tmp_path, store, AuditLog(tmp_path / "data" / "audit.jsonl"), "P1", cfg,
                      google_client=lambda: FakeGoogleClient(), eventkit_client=lambda: eventkit.FakeEventKitClient(),
                      notes_runner=FakeNotesRunner(), now=lambda: NOW)
    yield d
    store.close()


def test_shipped_config_defaults_are_safe():
    cfg = load_connectors_config()
    assert cfg["gmail"]["header_class"] == "P2" and cfg["gmail"]["body_class"] == "P2"
    assert cfg["docs"]["default_class"] == "P2"
    assert cfg["google"]["client_secret_file"] == ""  # never a real path in the public repo
    assert cfg["timezone"] == "Asia/Kolkata"


def test_connector_tools_and_tiers(deps, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")  # Apple Notes registers only on macOS
    tiers = {t.spec.name: t.tier for t in connector_tools(deps)}
    assert tiers == {"doc_search": "T0", "parse_time": "T0", "calendar_list": "T0", "calendar_create_event": "T2",
                     "gmail_search": "T0", "gmail_read": "T0", "gmail_draft": "T1", "gmail_send": "T3",
                     "reminders_list": "T2", "reminder_create": "T2",
                     "notes_search": "T0", "notes_read": "T0", "notes_create": "T1"}


def test_unclassified_tools_default_to_t2_and_no_agents():
    assert declared("some_new_tool") == {"tier": "T2", "agents": [], "unclassified": True}
    assert declared("reminder_create")["agents"] == []
    t = Tool(ToolSpec("some_new_tool", "x", {"type": "object", "properties": {}}), "T0", lambda a: "ok")
    assert _with_declared_tier(t).tier == "T2"
    # a declared tier never lowers what the code asks for
    t3 = Tool(ToolSpec("doc_search", "x", {"type": "object", "properties": {}}), "T3", lambda a: "ok")
    assert _with_declared_tier(t3).tier == "T3"


def test_google_eventkit_and_notes_can_be_disabled(deps, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    cfg = dict(deps.cfg, google={"enabled": False}, eventkit={"enabled": False}, notes={"enabled": False})
    names = {t.spec.name for t in connector_tools(replace(deps, cfg=cfg))}
    assert names == {"doc_search"}


def test_eventkit_is_mac_only(deps, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    names = {t.spec.name for t in connector_tools(replace(deps, eventkit_client=None))}
    assert "reminders_list" not in names
    ok, detail = eventkit.health()
    assert not ok and "needs macOS" in detail
    assert eventkit.default_client() is None


def test_eventkit_fake_create_is_t2_and_verified(deps, tmp_path):
    fake = eventkit.FakeEventKitClient()
    asked = []
    reg = ToolRegistry(deps.store, deps.audit, ApprovalGate(deps.store, deps.audit, lambda r: asked.append(r) or True))
    for t in connector_tools(replace(deps, eventkit_client=lambda: fake)):
        reg.register(t)
    res = reg.execute(ToolCall("c", "reminder_create", {"title": "Water the demo plants", "due": "2026-10-11T09:00"}))
    assert "[verified: reminder read back]" in res.content and asked[0].tier == "T2"
    assert eventkit.health(lambda: fake) == (True, "Reminders access granted")
    assert not eventkit.health(lambda: eventkit.FakeEventKitClient(access="denied"))[0]


def test_health_offline(deps, tmp_path):
    docs = tmp_path / "projects" / "garden" / "docs"
    docs.mkdir(parents=True)
    shutil.copy(FIXTURES / "notes.txt", docs)
    doc_library(deps).index()
    health = {name: (ok, detail) for name, ok, detail in connector_health(deps)}
    assert health["documents"][0] and "1 documents (1 private)" in health["documents"][1]
    assert health["google client file"] == (False, "not set (google.client_secret_file in config/local.yaml)")
    assert health["google token"][0] is False and "jarvis google auth" in health["google token"][1]
    import importlib.util
    installed = importlib.util.find_spec("googleapiclient") is not None  # optional extra [google]
    assert health["google libraries"][0] is installed
    assert "eventkit" in health


def test_health_live_records_last_check_and_expiry(deps):
    auth.save_token("r-token", auth.SCOPES, "cid", issued=date.today())
    health = {n: (ok, d) for n, ok, d in connector_health(deps, live=True)}
    assert health["google token"][0] and "Testing mode" in health["google token"][1]
    assert health["google last check"][0] and "fake client OK" in health["google last check"][1]

    failing = replace(deps, google_client=lambda: FakeGoogleClient(fail=True))
    health = {n: (ok, d) for n, ok, d in connector_health(failing, live=True)}
    assert health["google last check"][0] is False and "fake network failure" in health["google last check"][1]


def test_registry_file_sections_disable_and_raise(deps, tmp_path):
    tools = connector_tools(deps)
    path = tmp_path / "connectors" / "registry.yaml"
    write_connector_registry(tools, path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    g = data["connectors"]["google"]
    assert g["type"] == "direct-api" and g["auth"]["keyring_item"] == "google_oauth_token"
    assert g["tools"]["gmail_send"] == {"tier": "T3", "enabled": True, "agents": ["jarvis"]}
    assert data["connectors"]["eventkit"]["tools"]["reminder_create"]["agents"] == []
    assert "refresh" not in path.read_text(encoding="utf-8")

    g["tools"]["gmail_send"]["tier"] = "T1"          # lowering: ignored
    g["tools"]["gmail_draft"]["tier"] = "T2"         # raising: applied
    g["tools"]["gmail_search"]["enabled"] = False
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    write_connector_registry(tools, path)            # keeps Sachin's edits
    reg = ToolRegistry(deps.store, deps.audit)
    for t in tools:
        reg.register(t)
    apply_connector_registry(reg, path, deps.audit)
    assert reg.get("gmail_send").tier == "T3"
    assert reg.get("gmail_draft").tier == "T2"
    assert reg.get("gmail_search").enabled is False


# ---- CLI ----

def _parse(argv):
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    cli_connectors.register(sub)
    return p.parse_args(argv)


def _run(argv):
    out = io.StringIO()
    args = _parse(argv)
    code = cli_connectors.handlers(args, out)[args.command]()
    return code, out.getvalue()


def test_cli_docs_index_search_mark_list(tmp_path):
    docs = tmp_path / "projects" / "garden" / "docs"
    docs.mkdir(parents=True)
    shutil.copy(FIXTURES / "garden-plan.md", docs)
    code, out = _run(["docs", "index"])
    assert code == 0 and "1 added" in out
    code, out = _run(["docs", "index", "--project", "garden"])
    assert "1 unchanged" in out
    code, out = _run(["docs", "search", "rain", "barrel"])
    assert '[garden-plan.md, section "Watering"]' in out and "P2" in out
    code, out = _run(["docs", "mark", "garden-plan.md", "--class", "P1"])
    assert code == 0 and "garden/garden-plan.md is now P1" in out
    code, out = _run(["docs", "list"])
    assert "P1  garden/garden-plan.md" in out
    code, out = _run(["docs", "mark", "nope.md", "--class", "P1", "--project", "garden"])
    assert code == 1 and "Error" in out


def test_cli_calendar_list_with_fake(monkeypatch):
    fake = FakeGoogleClient(events=[{"id": "e9", "summary": "Demo review",
                                     "start": {"dateTime": datetime.now(get_tz("Asia/Kolkata")).replace(
                                         hour=23, minute=0, second=0, microsecond=0).isoformat()},
                                     "end": {"dateTime": datetime.now(get_tz("Asia/Kolkata")).replace(
                                         hour=23, minute=30, second=0, microsecond=0).isoformat()}}])
    monkeypatch.setattr(cli_connectors, "GOOGLE_CLIENT_FACTORY", lambda cfg: (lambda: fake))
    code, out = _run(["calendar", "list"])
    assert code == 0 and "Demo review" in out


def test_cli_google_status_offline(tmp_path):
    code, out = _run(["google", "status"])
    assert code == 0 and "google token: NOT OK" in out
