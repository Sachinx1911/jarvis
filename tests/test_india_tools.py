"""India chat tools, document wallet and wiring: risk tiers, P2 withholding below P2 routes,
Aadhaar/PAN masking, the brief showing only counts by default, and catalog/CLI/brief wiring.

All data here is synthetic: example billers, made-up names and numbers.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.india.brief_sections import DueSoonSection
from jarvis.india.net import FakeFetcher
from jarvis.india.tools import IndiaDeps, india_tools
from jarvis.proactive.brief import BriefContext
from jarvis.tools.catalog import ToolDeps, build_registry
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=IST)
BILL_TEXT = ("Dear Consumer, Consumer No 170012345678. Bill amount Rs. 1,234.50 for September 2026. "
             "Due date: 15-10-2026. Pay before due date to avoid late fee.")
FAKE_AADHAAR = "2345 6789 0123"   # made-up, pattern only
FAKE_PAN = "ABCDE1234F"           # made-up, pattern only


def cfg(details: bool = False) -> dict:
    return {
        "timezone": "Asia/Kolkata",
        "brief": {"details": details},
        "nav": {"enabled": True, "url": "https://example.test/NAVAll.txt", "schemes": []},
        "bills": {"reminder_lead_days": 3, "reminder_hour": 9, "privacy_class": "P2",
                  "billers": [{"name": "MSEDCL", "match": ["msedcl", "consumer no"], "category": "electricity"}]},
        "wallet": {"default_lead_days": 30, "reminder_hour": 9},
    }


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    (tmp_path / "workspace").mkdir()

    def tools(max_privacy: str = "P1", details: bool = False) -> dict:
        deps = IndiaDeps(tmp_path, store, audit, max_privacy=max_privacy, cfg=cfg(details),
                         fetcher=FakeFetcher({}), now=lambda: NOW)
        return {t.spec.name: t for t in india_tools(deps)}

    yield tmp_path, store, audit, tools
    store.close()


def test_tiers_are_as_designed(env):
    *_, tools = env
    assert {n: t.tier for n, t in tools().items()} == {
        "mf_nav": "T0", "bills_list": "T0", "bill_add": "T1",
        "bill_upi_link": "T3", "wallet_list": "T0", "wallet_add": "T1"}


def test_bill_details_are_withheld_below_p2(env):
    *_, tools = env
    out = tools("P1")["bill_add"].handler({"text": BILL_TEXT, "sender": "billing@msedcl.example"})
    assert out.startswith("Tracked bill #")
    p1 = tools("P1")["bills_list"].handler({})
    assert "withheld" in p1.lower() and "MSEDCL" not in p1 and "1,234" not in p1
    assert "1 due bills tracked" in p1 or "1 due" in p1
    p2 = tools("P2")["bills_list"].handler({})
    assert "MSEDCL" in p2


def test_upi_link_is_withheld_below_p2(env):
    *_, tools = env
    tools("P2")["bill_add"].handler({"text": BILL_TEXT})
    out = tools("P1")["bill_upi_link"].handler({"bill_id": 1})
    assert "private" in out.lower() and "upi://" not in out


def test_wallet_masks_numbers_and_never_stores_them(env):
    _, store, _, tools = env
    out = tools("P2")["wallet_add"].handler({
        "doc_type": "pan", "holder": "Example Person", "number": FAKE_PAN,
        "notes": f"linked to aadhaar {FAKE_AADHAAR}", "expiry": "2031-01-01"})
    assert out.startswith("Saved wallet record #") and "masked" in out
    rows = store.conn.execute("SELECT number_masked, notes FROM india_wallet").fetchall()
    dump = repr([tuple(r) for r in rows])
    assert FAKE_PAN not in dump and FAKE_AADHAAR not in dump and "56789" not in dump
    assert "234F" in dump and "0123" in dump  # only the last 4 survive
    listing = tools("P2")["wallet_list"].handler({})
    assert "Example Person" in listing and FAKE_PAN not in listing


def test_wallet_list_withheld_below_p2(env):
    *_, tools = env
    tools("P2")["wallet_add"].handler({"doc_type": "passport", "holder": "Example Person", "expiry": "2026-10-30"})
    out = tools("P1")["wallet_list"].handler({})
    assert "withheld" in out.lower() and "Example Person" not in out and "1 documents" in out


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/hosts", "C:/Windows/win.ini"])
def test_wallet_file_must_stay_in_workspace(env, bad):
    *_, tools = env
    out = tools("P2")["wallet_add"].handler({"doc_type": "other", "holder": "Example Person", "file": bad})
    assert out.startswith("Not saved") or "file not found yet" in out
    if out.startswith("Saved"):
        # a Windows path on a Mac is only a (missing) name inside the workspace, never outside it
        assert bad.startswith("C:")


def test_wallet_expiry_sets_two_reminders(env):
    *_, tools = env
    out = tools("P2")["wallet_add"].handler({"doc_type": "insurance", "holder": "Example Person",
                                             "expiry": "2026-12-31", "lead_days": 30})
    assert "2 expiry reminder(s) set" in out


def _brief_ctx(tmp_path, store):
    return BriefContext(now=NOW, home=tmp_path, store=store, settings=None)


def test_brief_shows_only_counts_by_default(env):
    tmp_path, store, _, tools = env
    tools("P2")["bill_add"].handler({"text": BILL_TEXT})
    tools("P2")["wallet_add"].handler({"doc_type": "passport", "holder": "Example Person", "expiry": "2026-10-30"})
    text = DueSoonSection(cfg=cfg(details=False)).render(_brief_ctx(tmp_path, store))
    assert "1 bill(s) due within 7 days" in text and "1 document(s) expiring soon" in text
    assert "MSEDCL" not in text and "1,234" not in text and "Example Person" not in text


def test_brief_details_only_when_switched_on(env):
    tmp_path, store, _, tools = env
    tools("P2")["bill_add"].handler({"text": BILL_TEXT})
    text = DueSoonSection(cfg=cfg(details=True)).render(_brief_ctx(tmp_path, store))
    assert "MSEDCL" in text


def test_brief_section_silent_when_nothing_due(env):
    tmp_path, store, *_ = env
    assert DueSoonSection(cfg=cfg()).render(_brief_ctx(tmp_path, store)) is None


def test_registry_includes_india_tools_with_their_tiers(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit, None))
    build_registry(reg, ToolDeps(home=tmp_path, store=store, audit=audit, memory=None, skills=None,
                                 session_id=lambda: "s", max_privacy="P1", tools_config={}, web=WebClient(),
                                 quarantine=None, tavily_key=lambda: None, system=SystemTools()))
    tiers = {t.spec.name: t.tier for t in reg.all()}
    # bill_upi_link is declared T2 but has no undo or verify path: the astra rule (27.4a) raises it to T3
    assert tiers["mf_nav"] == "T0" and tiers["bill_upi_link"] == "T3" and tiers["wallet_add"] == "T1"
    store.close()


def test_cli_has_india_commands():
    from jarvis.cli import build_parser_with_extensions

    _, extra = build_parser_with_extensions()
    assert {"nav", "bills", "wallet", "imd"} <= set(extra)


def test_proactive_integration_registers_india_sections():
    import jarvis.proactive.integration  # noqa: F401  (registers sections on import)
    from jarvis.proactive.brief import registered_sections

    keys = {s.key for s in registered_sections()}
    assert {"india_alerts", "india_due", "india_nav", "india_news"} <= keys


def test_offline_tests_cannot_reach_the_internet():
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
