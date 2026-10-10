"""India tab API: NAVs (saved, refresh, schemes in local.yaml), bills (paste, list, paid/ignore),
the UPI hand-off (confirmed payee, hash of what was shown, never pays), the document wallet
(numbers masked, expiring soon) and tax-deadline reminders.

Offline: a fake AMFI fetcher and a fixed clock. All data is synthetic (example billers,
made-up names, numbers that only have the shape of an Aadhaar or PAN).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from jarvis.core.runtime import open_runtime  # noqa: E402
from jarvis.india.bills import BillStore  # noqa: E402
from jarvis.india.config import load_india_config, section, tz  # noqa: E402
from jarvis.india.net import FakeFetcher, FetchError  # noqa: E402
from tests.test_web_api_app import H, _client, audit_text  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=IST)
NAV_URL = "https://nav.example/NAVAll.txt"
BILL_TEXT = ("Dear Consumer, Consumer No 170012345678. Bill amount Rs. 1,234.50 for September 2026. "
             "Due date: 15-10-2026. Pay before due date to avoid late fee.")
BILL_TEXT_2 = "Your Example Broadband bill of Rs 799 is due on 20-10-2026. Amount due Rs 799."
FAKE_AADHAAR = "2345 6789 0123"   # made-up, pattern only
FAKE_PAN = "ABCDE1234F"           # made-up, pattern only
FAKE_VPA = "msedcl.example@okexample"
EVIL = "https://evil.example"

INDIA_YAML = f"""
timezone: Asia/Kolkata
nav:
  enabled: true
  url: {NAV_URL}
  refresh_hours: 12
  schemes:
    - {{code: "900001", label: "Example bluechip"}}
bills:
  reminder_lead_days: 3
  reminder_hour: 9
  privacy_class: P2
  billers:
    - {{name: MSEDCL, match: [msedcl, consumer no], category: electricity}}
wallet:
  default_lead_days: 30
  reminder_hour: 9
  types: [passport, pan, aadhaar, driving_licence, insurance, other]
tax:
  lead_days: 7
  deadlines:
    - {{name: "Example deadline B", date: 2027-03-15}}
    - {{name: "Example deadline A", date: 2026-12-15}}
    - {{name: "Example deadline past", date: 2026-07-31}}
"""


def nav_file(nav: str = "105.4321", day: str = "09-Oct-2026") -> bytes:
    return ("Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;"
            "Net Asset Value;Date\nOpen Ended Schemes(Equity Scheme - Large Cap Fund)\nExample Mutual Fund\n"
            f"900001;INF000X01AA1;-;Example Bluechip Fund;Direct Plan;Growth Option;{nav};{day}\n"
            "900002;INF000X01AB9;-;Example Midcap Fund;Direct Plan;Growth Option;55.5000;09-Oct-2026\n").encode()


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    (d / "india.yaml").write_text(INDIA_YAML, encoding="utf-8")
    return d


@pytest.fixture
def fetcher():
    return FakeFetcher({NAV_URL: nav_file()})


@pytest.fixture
def client(isolated, cfgdir, fetcher):
    (isolated / "workspace").mkdir(exist_ok=True)
    with _client(cfgdir, extra={"india_fetcher": fetcher, "india_clock": lambda: NOW}) as c:
        yield c


def add_bill(client, text: str = BILL_TEXT) -> dict:
    r = client.post("/api/india/bills", headers=H, json={"text": text, "sender": "billing@msedcl.example"})
    assert r.status_code == 200, r.text
    return r.json()["bill"]


def add_payee(cfgdir, vpa: str = FAKE_VPA) -> None:
    """What `jarvis bills payee-add` does after Sachin confirms the UPI ID himself in the terminal."""
    cfg = load_india_config(cfgdir)
    rt = open_runtime()
    try:
        BillStore(rt.store.conn, tz(cfg), rt.audit, section(cfg, "bills")).add_payee("MSEDCL", vpa, "MSEDCL", NOW)
    finally:
        rt.close()


def db_bytes(home) -> bytes:
    return b"".join(p.read_bytes() for p in (home / "data").glob("jarvis.db*"))


# ---- token and origin on every India route ----

ROUTES = [("get", "/api/india/nav"), ("post", "/api/india/nav/refresh"), ("post", "/api/india/nav/schemes"),
          ("get", "/api/india/bills"), ("post", "/api/india/bills"), ("post", "/api/india/bills/1/paid"),
          ("post", "/api/india/bills/1/ignore"), ("get", "/api/india/bills/1/upi"), ("post", "/api/india/bills/1/upi"),
          ("get", "/api/india/wallet"), ("post", "/api/india/wallet"), ("post", "/api/india/wallet/1/remove"),
          ("post", "/api/india/tax/reminders")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_india_routes_need_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"X-Jarvis-Token": "wrong"}).status_code == 401


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[0] == "post"])
def test_india_changes_refuse_foreign_origin(client, method, path, isolated):
    for extra in ({"Origin": EVIL}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.post(path, headers={**H, **extra}, json={"text": BILL_TEXT, "confirm": True})
        assert r.status_code == 403, path
    assert client.get("/api/india/bills?status=all", headers=H).json()["items"] == []


# ---- NAVs ----

def test_nav_saved_only_until_refresh(client, fetcher, isolated):
    d = client.get("/api/india/nav", headers=H).json()
    assert d["schemes"] == [{"code": "900001", "label": "Example bluechip"}]
    assert d["items"][0]["nav"] is None and d["fresh"] is False and d["last_fetch"] is None
    assert fetcher.calls == []  # GET never fetches
    r = client.post("/api/india/nav/refresh", headers=H).json()
    assert r["error"] is None and r["fresh"] is True
    assert r["items"][0] == {**r["items"][0], "code": "900001", "label": "Example bluechip", "nav": 105.4321,
                             "nav_date": "2026-10-09"}
    assert [u for u, _ in fetcher.calls] == [NAV_URL]  # only the configured public URL
    found = client.get("/api/india/nav?q=midcap", headers=H).json()["items"]
    assert [x["code"] for x in found] == ["900002"]
    assert '"india_nav_refreshed"' in audit_text(isolated)


def test_nav_refresh_failure_keeps_saved_values(client, fetcher):
    client.post("/api/india/nav/refresh", headers=H)
    fetcher.responses[NAV_URL] = FetchError("HTTP 503 from nav.example")
    r = client.post("/api/india/nav/refresh", headers=H).json()
    assert "unavailable" in r["error"] and r["items"][0]["nav"] == 105.4321


def test_nav_change_since_last_fetch(isolated, cfgdir):
    clock = {"now": NOW}
    fake = FakeFetcher({NAV_URL: nav_file("100.0000", "08-Oct-2026")})
    with _client(cfgdir, extra={"india_fetcher": fake, "india_clock": lambda: clock["now"]}) as c:
        c.post("/api/india/nav/refresh", headers=H)
        clock["now"] = NOW + timedelta(days=1)
        fake.responses[NAV_URL] = nav_file("102.5000", "09-Oct-2026")
        q = c.post("/api/india/nav/refresh", json={"force": False}, headers=H).json()["items"][0]
        assert q["nav"] == 102.5 and q["prev_nav"] == 100.0 and q["change"] == 2.5 and q["change_pct"] == 2.5


def test_nav_schemes_written_to_local_yaml(client, cfgdir, isolated):
    import yaml

    body = {"schemes": [{"code": "900002", "label": "  Example\nmidcap "}, {"code": "900002", "label": "dup"},
                        {"code": "900001", "label": ""}]}
    r = client.post("/api/india/nav/schemes", headers=H, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["schemes"] == [{"code": "900002", "label": "Example midcap"}, {"code": "900001", "label": "900001"}]
    local = yaml.safe_load((cfgdir / "local.yaml").read_text(encoding="utf-8"))
    assert local["india_file"]["nav"]["schemes"][0] == {"code": "900002", "label": "Example midcap"}
    assert client.post("/api/india/nav/schemes", headers=H, json={"schemes": [{"code": "12ab"}]}).status_code == 422
    too_many = {"schemes": [{"code": str(100000 + i)} for i in range(31)]}
    assert client.post("/api/india/nav/schemes", headers=H, json=too_many).status_code == 422
    assert "india_nav_schemes" not in client.get("/api/setup", headers=H).json()["config"]  # Setup tab unchanged
    assert '"local_config_changed"' in audit_text(isolated)


# ---- bills ----

def test_bill_paste_list_and_mark(client, fetcher, isolated):
    b = add_bill(client)
    assert (b["biller"], b["category"], b["amount"], b["due_date"]) == ("MSEDCL", "electricity", "Rs 1,234.50",
                                                                        "2026-10-15")
    assert b["status"] == "due" and b["days_left"] == 5 and b["reminders"] == 2 and b["payee"] is False
    assert client.post("/api/india/bills", headers=H, json={"text": BILL_TEXT}).status_code == 409  # same text
    assert client.post("/api/india/bills", headers=H, json={"text": "see you at 6 pm"}).status_code == 400
    other = add_bill(client, BILL_TEXT_2)

    d = client.get("/api/india/bills", headers=H).json()
    assert [x["id"] for x in d["items"]] == [b["id"], other["id"]]
    assert d["counts"] == {"due": 2, "due_soon": 1, "overdue": 0}
    assert "Bills for October 2026" in d["summary"] and d["payees"] == []

    assert client.post(f"/api/india/bills/{b['id']}/paid", headers=H).json()["bill"]["status"] == "paid"
    assert client.post(f"/api/india/bills/{b['id']}/paid", headers=H).status_code == 409
    assert client.post(f"/api/india/bills/{other['id']}/ignore", headers=H).json()["bill"]["status"] == "ignored"
    assert client.get("/api/india/bills", headers=H).json()["items"] == []
    assert [x["id"] for x in client.get("/api/india/bills?status=paid", headers=H).json()["items"]] == [b["id"]]
    assert [x["id"] for x in client.get("/api/india/bills?status=ignored", headers=H).json()["items"]] == [other["id"]]
    assert len(client.get("/api/india/bills?status=all&month=2026-10", headers=H).json()["items"]) == 1
    assert client.get("/api/india/bills?month=2026-13", headers=H).status_code == 400
    assert client.post("/api/india/bills/999/paid", headers=H).status_code == 404

    # Only extracted fields are kept; the pasted text is not in the database or the audit log.
    log = audit_text(isolated)
    assert "Consumer No" not in log and "1,234" not in log and "MSEDCL" not in log
    assert b"Consumer No 170012345678" not in db_bytes(isolated)
    assert '"india_bill_marked"' in log and fetcher.calls == []  # bills never touch the network


# ---- UPI hand-off ----

def test_upi_needs_confirmed_payee_and_matching_hash(client, cfgdir, isolated, monkeypatch):
    from jarvis.india import upi

    monkeypatch.setattr(upi, "save_qr", lambda link, path: None)  # same result with or without `qrcode`
    b = add_bill(client)
    p = client.get(f"/api/india/bills/{b['id']}/upi", headers=H).json()
    assert p["ready"] is False and "no confirmed payee" in p["reason"] and "payee-add" in p["reason"]
    r = client.post(f"/api/india/bills/{b['id']}/upi", headers=H, json={"confirm": True, "args_sha256": "x"})
    assert r.status_code == 409

    add_payee(cfgdir)
    preview = client.get(f"/api/india/bills/{b['id']}/upi", headers=H)
    p = preview.json()
    assert p["ready"] is True and p["payee"]["vpa"] == FAKE_VPA and len(p["args_sha256"]) == 64
    assert "upi://" not in preview.text  # looking never makes the link

    url = f"/api/india/bills/{b['id']}/upi"
    assert client.post(url, headers=H, json={"args_sha256": p["args_sha256"]}).status_code == 400  # no confirm
    assert client.post(url, headers=H, json={"confirm": True, "args_sha256": "0" * 64}).status_code == 409
    client.post("/api/stop", headers=H, json={"engaged": True})
    assert client.post(url, headers=H, json={"confirm": True, "args_sha256": p["args_sha256"]}).status_code == 409
    client.post("/api/stop", headers=H, json={"engaged": False})

    r = client.post(url, headers=H, json={"confirm": True, "args_sha256": p["args_sha256"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["link"].startswith(f"upi://pay?pa={FAKE_VPA}&pn=MSEDCL&am=1234.50&cu=INR")
    assert "does not pay" in out["note"] and out["qr"] is None
    assert '"india_upi_link_shown"' in audit_text(isolated) and FAKE_VPA not in audit_text(isolated)

    # The payee changes after Sachin looked: the old confirmation no longer counts.
    add_payee(cfgdir, "other.example@okexample")
    assert client.post(url, headers=H, json={"confirm": True, "args_sha256": p["args_sha256"]}).status_code == 409

    client.post(f"/api/india/bills/{b['id']}/paid", headers=H)
    p = client.get(url, headers=H).json()
    assert p["ready"] is False and "not due" in p["reason"]
    assert client.get("/api/india/bills/999/upi", headers=H).status_code == 404


def test_upi_qr_shown_when_qrcode_is_installed(client, cfgdir, monkeypatch):
    from jarvis.india import upi

    def fake_qr(link, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return path

    monkeypatch.setattr(upi, "save_qr", fake_qr)
    b = add_bill(client)
    add_payee(cfgdir)
    p = client.get(f"/api/india/bills/{b['id']}/upi", headers=H).json()
    out = client.post(f"/api/india/bills/{b['id']}/upi", headers=H,
                      json={"confirm": True, "args_sha256": p["args_sha256"]}).json()
    assert out["qr"].startswith("data:image/png;base64,")


# ---- document wallet ----

def test_wallet_masks_numbers_everywhere(client, isolated):
    body = {"doc_type": "aadhaar", "holder": "Asha Example", "number": FAKE_AADHAAR,
            "label": f"card {FAKE_PAN}", "notes": f"copy says {FAKE_AADHAAR}"}
    r = client.post("/api/india/wallet", headers=H, json=body)
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["number_masked"] == "XXXX0123" and rec["label"] == "card XXXXXX234F"
    assert any("masked" in w for w in r.json()["warnings"])
    listing = client.get("/api/india/wallet", headers=H)
    for text in (r.text, listing.text, audit_text(isolated)):
        assert FAKE_AADHAAR not in text and "234567890123" not in text and FAKE_PAN not in text
    blob = db_bytes(isolated)
    assert FAKE_AADHAAR.encode() not in blob and b"234567890123" not in blob and FAKE_PAN.encode() not in blob

    # A refused request never echoes what was typed.
    bad = client.post("/api/india/wallet", headers=H, json={**body, "lead_days": -1})
    assert bad.status_code == 422 and FAKE_AADHAAR not in bad.text and FAKE_PAN not in bad.text


def test_wallet_expiring_soon_and_remove(client, isolated):
    soon = client.post("/api/india/wallet", headers=H, json={"doc_type": "passport", "holder": "Asha Example",
                                                             "expiry": "2026-10-30", "number": "Z1234567"}).json()
    later = client.post("/api/india/wallet", headers=H, json={"doc_type": "insurance", "holder": "Asha Example",
                                                              "expiry": "2027-06-01", "label": "Example car policy"})
    old = client.post("/api/india/wallet", headers=H, json={"doc_type": "other", "holder": "Ravi Example",
                                                            "expiry": "2026-09-01"})
    assert soon["record"]["expiring_soon"] is True and soon["record"]["days_left"] == 20
    assert soon["record"]["number_masked"] == "XXXX4567" and soon["record"]["reminders"] >= 1
    assert later.json()["record"]["expiring_soon"] is False and old.json()["record"]["expired"] is True
    d = client.get("/api/india/wallet", headers=H).json()
    assert d["expiring_soon"] == 2 and "passport" in d["types"] and d["default_lead_days"] == 30
    assert [x["id"] for x in d["items"]][0] == old.json()["record"]["id"]  # sorted by expiry

    assert client.post("/api/india/wallet", headers=H, json={"doc_type": "ration", "holder": "A"}).status_code == 400
    assert client.post("/api/india/wallet", headers=H,
                       json={"doc_type": "pan", "holder": "A", "expiry": "soon"}).status_code == 400
    outside = client.post("/api/india/wallet", headers=H, json={"doc_type": "pan", "holder": "A", "file": "../x.pdf"})
    assert outside.status_code == 400 and "workspace" in outside.text

    rid = soon["record"]["id"]
    assert client.post(f"/api/india/wallet/{rid}/remove", headers=H, json={}).status_code == 400
    assert client.post(f"/api/india/wallet/{rid}/remove", headers=H, json={"confirm": True}).json() == {"removed": rid}
    assert client.post(f"/api/india/wallet/{rid}/remove", headers=H, json={"confirm": True}).status_code == 404
    assert '"india_wallet_record_removed"' in audit_text(isolated)


# ---- tax deadlines ----

def test_tax_deadlines_from_config_and_reminders_once(client):
    tax = client.get("/api/india/wallet", headers=H).json()["tax"]
    assert [x["name"] for x in tax["deadlines"]] == ["Example deadline past", "Example deadline A",
                                                     "Example deadline B"]
    assert tax["deadlines"][0]["past"] is True and tax["deadlines"][1]["days_left"] == 66
    assert not any(x["reminders_set"] for x in tax["deadlines"])
    r = client.post("/api/india/tax/reminders", headers=H).json()
    assert r["scheduled"] == ["Example deadline B", "Example deadline A"]
    assert [x["reminders_set"] for x in r["tax"]["deadlines"]] == [False, True, True]
    assert client.post("/api/india/tax/reminders", headers=H).json()["scheduled"] == []  # once each
    texts = [x["text"] for x in client.get("/api/reminders", headers=H).json()["items"]]
    assert any("Example deadline A" in t for t in texts)
