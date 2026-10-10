"""Weather and disaster alerts (NDMA Sachet, IMD) and Marathi news headlines.

Sources (checked 2026-10-10):
- NDMA Sachet CAP RSS: https://sachet.ndma.gov.in/cap_public_website/rss/rss_<state>.xml
  (state list from sachet.ndma.gov.in/CapFeed). RSS 2.0; each <item> has title (the alert
  text, often Marathi for Maharashtra), category (e.g. Met), link (CAP XML), author (issuing
  office), guid and pubDate (RFC 822, GMT).
- IMD API gateway: https://api.imd.gov.in/api/v1/districtwarning?id=<district id>. Fields per
  the official reference: Obj_id, Date, UTC, District, Day_1..Day_5 (comma-separated warning
  codes 1-17), Day1_Color..Day5_Color (1 red, 2 orange, 3 yellow, 4 green). Without a key it
  answers 401 "API key missing"; with X-API-Key it also wants "Authorization: Bearer <JWT>".
  How IMD issues the key and JWT to an individual is NOT confirmed (onboarding by IMD).
- BBC News Marathi RSS: https://feeds.bbci.co.uk/marathi/rss.xml (the publisher's own feed).

Feed text is outside text: shown to Sachin as-is (one line, capped), never followed.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from jarvis.india.net import Fetcher, FetchError

MAX_TITLE = 300


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    published: datetime | None
    category: str = ""
    author: str = ""
    guid: str = ""


def _clean(text: str | None, limit: int = MAX_TITLE) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def parse_rss(data: bytes) -> list[FeedItem]:
    if b"<!DOCTYPE" in data[:2000].upper() and b"<rss" not in data[:4000]:
        raise ValueError("not an RSS feed (got an HTML page)")
    if b"<!ENTITY" in data:
        raise ValueError("feed declares entities; refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"feed is not valid XML: {e}") from e
    items = []
    for it in root.iter("item"):
        published = None
        raw = it.findtext("pubDate")
        if raw:
            try:
                published = parsedate_to_datetime(raw.strip())
            except (TypeError, ValueError):
                published = None
        items.append(FeedItem(_clean(it.findtext("title")), (it.findtext("link") or "").strip(), published,
                              _clean(it.findtext("category"), 40), _clean(it.findtext("author"), 80),
                              (it.findtext("guid") or "").strip()))
    return items


# ---------------------------------------------------------------- Sachet alerts


def sachet_url(cfg: dict[str, Any]) -> str:
    pattern = str(cfg.get("sachet_url") or "https://sachet.ndma.gov.in/cap_public_website/rss/rss_{state}.xml")
    state = re.sub(r"[^a-z]", "", str(cfg.get("state") or "maharashtra").lower())
    return pattern.format(state=state)


def _district_names(cfg: dict[str, Any]) -> list[tuple[str, list[str]]]:
    out = []
    for d in cfg.get("districts") or []:
        if isinstance(d, str):
            out.append((d, [d]))
        elif isinstance(d, dict) and d.get("name"):
            out.append((str(d["name"]), [str(d["name"])] + [str(a) for a in d.get("aliases") or []]))
    return out


def select_alerts(items: list[FeedItem], cfg: dict[str, Any], now: datetime) -> tuple[list[FeedItem], int]:
    """Recent alerts that name one of the configured districts (all recent ones if none are set).
    Returns (shown, other recent state alerts not naming a configured district)."""
    since = now - timedelta(hours=float(cfg.get("hours") or 24))
    recent = [i for i in items if i.published is None or i.published >= since]
    districts = _district_names(cfg)
    if not districts:
        return recent, 0
    shown = [i for i in recent if any(a.lower() in i.title.lower() for _, names in districts for a in names)]
    return shown, len(recent) - len(shown)


def sachet_alerts(fetcher: Fetcher, cfg: dict[str, Any], now: datetime) -> tuple[list[FeedItem], int]:
    return select_alerts(parse_rss(fetcher.get(sachet_url(cfg))), cfg, now)


# ---------------------------------------------------------------- IMD district warnings

IMD_WARNINGS = {
    1: "No warning", 2: "Heavy rain", 3: "Heavy snow", 4: "Thunderstorm & lightning, squall", 5: "Hailstorm",
    6: "Dust storm", 7: "Dust-raising winds", 8: "Strong surface winds", 9: "Heat wave", 10: "Hot day",
    11: "Warm night", 12: "Cold wave", 13: "Cold day", 14: "Ground frost", 15: "Fog", 16: "Very heavy rain",
    17: "Extremely heavy rain",
}
IMD_WARNING_COLORS = {1: "RED", 2: "ORANGE", 3: "YELLOW", 4: "green"}


@dataclass(frozen=True)
class DistrictWarning:
    district: str
    day: int
    warnings: list[str]
    color: str


def parse_imd_district_warnings(data: bytes, days: int = 2) -> list[DistrictWarning]:
    payload = json.loads(data.decode("utf-8"))
    rows = payload if isinstance(payload, list) else (payload.get("data") or payload.get("result") or [payload])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for day in range(1, days + 1):
            codes = [int(c) for c in re.findall(r"\d+", str(row.get(f"Day_{day}", "")))]
            warn = [IMD_WARNINGS.get(c, f"code {c}") for c in codes if c != 1]
            try:
                color = IMD_WARNING_COLORS.get(int(row.get(f"Day{day}_Color") or 4), "?")
            except (TypeError, ValueError):
                color = "?"
            if warn:
                out.append(DistrictWarning(_clean(str(row.get("District") or "?"), 60), day, warn, color))
    return out


def imd_warnings(fetcher: Fetcher, cfg: dict[str, Any], api_key: str, jwt: str) -> list[DistrictWarning]:
    base = str(cfg.get("base_url") or "https://api.imd.gov.in/api/v1/").rstrip("/") + "/"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {jwt}"}
    out: list[DistrictWarning] = []
    for did in cfg.get("district_ids") or []:
        out += parse_imd_district_warnings(fetcher.get(f"{base}districtwarning?id={int(did)}", headers))
    return out


# ---------------------------------------------------------------- news


def news_headlines(fetcher: Fetcher, cfg: dict[str, Any]) -> list[FeedItem]:
    url = str(cfg.get("url") or "")
    if not url:
        raise FetchError("no news feed URL set")
    return parse_rss(fetcher.get(url))[: int(cfg.get("max_items") or 5)]
