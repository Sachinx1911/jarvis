"""India data feeds: AMFI NAV parsing and change, Sachet/IMD alerts, Marathi news, brief sections.

All offline: a FakeFetcher serves synthetic fixtures; nothing touches the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.db import Store
from jarvis.india import feeds
from jarvis.india.brief_sections import AlertsSection, NavSection, NewsSection, india_sections, register_india_sections
from jarvis.india.nav import NavService, parse_nav_all
from jarvis.india.net import FakeFetcher, FetchError, UrlFetcher
from jarvis.proactive import brief
from jarvis.proactive.brief import BriefContext, build_brief

FIX = Path(__file__).parent / "fixtures" / "india"
IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=IST)
NAV_URL = "https://nav.example/NAVAll.txt"
SACHET_URL = "https://sachet.example/rss_maharashtra.xml"
NEWS_URL = "https://news.example/rss.xml"


def cfg(**over) -> dict:
    base = {
        "timezone": "Asia/Kolkata",
        "nav": {"enabled": True, "url": NAV_URL, "refresh_hours": 12,
                "schemes": [{"code": "900001", "label": "Bluechip"}, {"code": "900010", "label": "Index"}]},
        "alerts": {"enabled": True, "sachet_url": "https://sachet.example/rss_{state}.xml", "state": "maharashtra",
                   "hours": 24, "districts": [{"name": "Pune", "aliases": ["पुणे"]}]},
        "imd": {"enabled": False, "base_url": "https://imd.example/api/v1/", "district_ids": [573]},
        "news": {"enabled": True, "url": NEWS_URL, "source": "Example Marathi", "max_items": 5},
        "bills": {}, "wallet": {},
    }
    base.update(over)
    return base


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "j.db")
    yield s
    s.close()


# ---------------------------------------------------------------- NAV


def test_parse_current_8_column_file():
    rows = {r.code: r for r in parse_nav_all(fixture("navall_sample.txt").decode())}
    assert set(rows) == {"900001", "900002", "900010"}          # N.A. row skipped
    assert rows["900001"].nav == pytest.approx(105.4321)
    assert rows["900001"].name == "Example Bluechip Fund - Direct Plan - Growth Option"
    assert rows["900001"].nav_date.isoformat() == "2026-10-09"
    assert rows["900001"].amc == "Example Mutual Fund"
    assert rows["900010"].nav == pytest.approx(1234.5678)       # thousands separator
    assert rows["900010"].amc == "Sample Asset Management"
    assert rows["900002"].isin2 == "INF000X01AC7"


def test_parse_older_6_column_file():
    rows = parse_nav_all(fixture("navall_sample_old.txt").decode())
    assert [(r.code, r.nav) for r in rows] == [("900020", pytest.approx(3456.789))]


def test_parse_rejects_non_amfi_text():
    with pytest.raises(ValueError):
        parse_nav_all("<html>maintenance</html>")


def _nav_file(nav: str, day: str) -> bytes:
    return (f"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;"
            f"Net Asset Value;Date\nExample Mutual Fund\n900001;INF0;-;Example Bluechip Fund;Direct Plan;"
            f"Growth Option;{nav};{day}\n").encode()


def test_nav_change_since_last_fetch_and_daily_cache(store):
    clock = {"now": NOW}
    fetcher = FakeFetcher({NAV_URL: _nav_file("100.0000", "08-Oct-2026")})
    svc = NavService(store.conn, cfg(), fetcher, lambda: clock["now"])
    assert svc.refresh() is None
    first = svc.quote("900001", "Bluechip")
    assert first.nav == 100 and first.change is None

    # Within refresh_hours: no new fetch (cached).
    clock["now"] = NOW + timedelta(hours=2)
    assert svc.refresh() is None
    assert len(fetcher.calls) == 1

    # Next day: fetched again, change computed against the previous NAV.
    fetcher.responses[NAV_URL] = _nav_file("102.5000", "09-Oct-2026")
    clock["now"] = NOW + timedelta(days=1)
    svc.refresh()
    q = svc.quote("900001", "Bluechip")
    assert len(fetcher.calls) == 2
    assert q.nav == 102.5 and q.change == pytest.approx(2.5) and q.change_pct == pytest.approx(2.5)
    assert "+2.5000 (+2.50%) since 08 Oct" in q.line()


def test_nav_fetch_failure_keeps_saved_values(store):
    svc = NavService(store.conn, cfg(), FakeFetcher({NAV_URL: _nav_file("100.0", "08-Oct-2026")}), lambda: NOW)
    svc.refresh()
    svc.fetcher = FakeFetcher({NAV_URL: FetchError("HTTP 503")})
    assert "unavailable" in svc.refresh(force=True)
    assert svc.quote("900001").nav == 100


def test_nav_search_by_name_and_code(store):
    svc = NavService(store.conn, cfg(), FakeFetcher({NAV_URL: fixture("navall_sample.txt")}), lambda: NOW)
    svc.refresh()
    assert [q.code for q in svc.search("nifty index")] == ["900010"]
    assert svc.search("900002")[0].nav == pytest.approx(22.1)


def test_url_fetcher_refuses_plain_http():
    with pytest.raises(FetchError):
        UrlFetcher().get("http://example.com/x")


# ---------------------------------------------------------------- alerts and news


def test_sachet_alerts_filtered_by_district_and_age():
    items = feeds.parse_rss(fixture("sachet_sample.xml"))
    assert len(items) == 3 and items[0].category == "Met"
    shown, others = feeds.select_alerts(items, cfg()["alerts"], NOW)
    assert [i.guid for i in shown] == ["1001"]      # Marathi district alias matched; week-old alert dropped
    assert others == 1                              # the Nagpur alert
    all_shown, _ = feeds.select_alerts(items, {"hours": 24}, NOW)
    assert [i.guid for i in all_shown] == ["1001", "1002"]


def test_sachet_url_from_state():
    assert feeds.sachet_url({"state": "Maharashtra"}).endswith("/rss/rss_maharashtra.xml")


def test_rss_refuses_entities_and_html():
    with pytest.raises(ValueError):
        feeds.parse_rss(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rss><channel/></rss>')
    with pytest.raises(ValueError):
        feeds.parse_rss(b"<!DOCTYPE html><html><body>not a feed</body></html>")


def test_imd_district_warning_parsing():
    warnings = feeds.parse_imd_district_warnings(fixture("imd_districtwarning.json"))
    assert len(warnings) == 1
    w = warnings[0]
    assert (w.district, w.day, w.color) == ("Example District", 1, "ORANGE")
    assert w.warnings == ["Heavy rain", "Thunderstorm & lightning, squall"]


def ctx(store, tmp_path, fetcher) -> BriefContext:
    return BriefContext(now=NOW, home=tmp_path, store=store, settings=None, extras={"india_fetcher": fetcher})


def test_alerts_section_skips_imd_politely_without_key(store, tmp_path):
    c = cfg(imd={"enabled": True, "district_ids": [573], "base_url": "https://imd.example/api/v1/"})
    fetcher = FakeFetcher({SACHET_URL: fixture("sachet_sample.xml")})
    text = AlertsSection(cfg=c, secret=lambda name: None).render(ctx(store, tmp_path, fetcher))
    assert "मेघगर्जनेसह" in text
    assert "1 other alert" in text
    assert "IMD warnings skipped" in text
    assert all("imd.example" not in url for url, _ in fetcher.calls)


def test_alerts_section_with_imd_key_sends_headers(store, tmp_path):
    c = cfg(imd={"enabled": True, "district_ids": [573], "base_url": "https://imd.example/api/v1/"})
    imd_url = "https://imd.example/api/v1/districtwarning?id=573"
    fetcher = FakeFetcher({SACHET_URL: fixture("sachet_sample.xml"), imd_url: fixture("imd_districtwarning.json")})
    secrets = {"imd_api_key": "test-key", "imd_jwt": "test-jwt"}
    text = AlertsSection(cfg=c, secret=secrets.get).render(ctx(store, tmp_path, fetcher))
    assert "IMD ORANGE today, Example District: Heavy rain" in text
    headers = dict(fetcher.calls)[imd_url]
    assert headers == {"X-API-Key": "test-key", "Authorization": "Bearer test-jwt"}


def test_alerts_section_feed_failure_is_one_line(store, tmp_path):
    text = AlertsSection(cfg=cfg()).render(ctx(store, tmp_path, FakeFetcher({SACHET_URL: FetchError("HTTP 500")})))
    assert text.startswith("- Sachet alerts unavailable")


def test_nav_section_and_news_section(store, tmp_path):
    fetcher = FakeFetcher({NAV_URL: fixture("navall_sample.txt"), NEWS_URL: fixture("news_sample.xml")})
    c = ctx(store, tmp_path, fetcher)
    nav = NavSection(cfg=cfg()).render(c)
    assert "- Bluechip: 105.4321 (09 Oct)" in nav and "- Index: 1,234.5678" in nav
    assert NewsSection(cfg=cfg()).render(c) == "- पहिली उदाहरण बातमी\n- दुसरी उदाहरण बातमी"
    assert NewsSection(cfg=cfg()).title == "Marathi headlines (Example Marathi)"
    assert NewsSection(cfg=cfg(news={"enabled": False})).render(c) is None
    assert NavSection(cfg=cfg(nav={"enabled": True, "url": NAV_URL, "schemes": []})).render(c) is None


def test_sections_fit_the_brief(store, tmp_path):
    fetcher = FakeFetcher({NAV_URL: fixture("navall_sample.txt"), NEWS_URL: fixture("news_sample.xml"),
                           SACHET_URL: fixture("sachet_sample.xml")})
    sections = india_sections(cfg=cfg(), secret=lambda n: None)
    for s in sections:
        assert isinstance(s, brief.BriefSection)
    result = build_brief(ctx(store, tmp_path, fetcher), sections=sections)
    assert result.failed == []
    assert "Weather and disaster alerts" in result.text and "Mutual fund NAVs" in result.text
    assert "Bills and documents due" not in result.text   # nothing due: section left out


def test_register_india_sections(monkeypatch):
    monkeypatch.setattr(brief, "_REGISTRY", dict(brief._REGISTRY))
    register_india_sections(cfg=cfg())
    keys = {s.key for s in brief.registered_sections()}
    assert {"india_alerts", "india_nav", "india_due", "india_news"} <= keys
