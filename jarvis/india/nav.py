"""Mutual fund NAVs from AMFI's public daily file (NAVAll.txt).

Format (checked 2026-10-10 at portal.amfiindia.com/spages/NAVAll.txt): a header line, then
section lines ("Open Ended Schemes(...)"), fund-house lines ("Axis Mutual Fund") and
semicolon-separated rows. The current header has 8 columns:
  Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
Older copies had 6 (no Plan/Option). Columns are found by header name, so both work.
Dates look like 09-Oct-2026. A NAV of "N.A." is skipped.

The file is fetched at most once per `refresh_hours`; every scheme's latest NAV is cached
(india_nav_latest) so lookups work offline, and the schemes Sachin lists keep a history
(india_nav_history) for "change since last fetch".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from jarvis.india.config import section
from jarvis.india.net import Fetcher, FetchError
from jarvis.india.text import parse_date

_SCHEMA = """
CREATE TABLE IF NOT EXISTS india_nav_latest (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, amc TEXT, isin1 TEXT, isin2 TEXT,
    nav REAL NOT NULL, nav_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS india_nav_history (
    code TEXT NOT NULL, nav_date TEXT NOT NULL, nav REAL NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (code, nav_date)
);
CREATE TABLE IF NOT EXISTS india_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class NavRow:
    code: str
    name: str
    nav: float
    nav_date: date
    amc: str = ""
    isin1: str = ""
    isin2: str = ""


def _col(header: list[str], *starts: str) -> int | None:
    for i, h in enumerate(header):
        low = h.strip().lower()
        if any(low.startswith(s) for s in starts):
            return i
    return None


def parse_nav_all(text: str) -> list[NavRow]:
    lines = [l.strip() for l in text.lstrip("﻿").splitlines()]
    header_at = next((i for i, l in enumerate(lines) if l.lower().startswith("scheme code;")), None)
    if header_at is None:
        raise ValueError("not an AMFI NAV file (no 'Scheme Code;' header)")
    header = lines[header_at].split(";")
    idx = {"code": _col(header, "scheme code"), "name": _col(header, "scheme name"),
           "plan": _col(header, "plan"), "option": _col(header, "option"),
           "nav": _col(header, "net asset value"), "date": _col(header, "date"),
           "isin1": _col(header, "isin div payout"), "isin2": _col(header, "isin div reinvestment")}
    if None in (idx["code"], idx["name"], idx["nav"], idx["date"]):
        raise ValueError("AMFI NAV header is missing a needed column")
    rows: list[NavRow] = []
    amc = ""
    for line in lines[header_at + 1:]:
        if not line:
            continue
        parts = line.split(";")
        if len(parts) != len(header):
            if ";" not in line and not line.lower().startswith(("open ended", "close ended", "interval fund")):
                amc = line  # fund-house line
            continue
        get = lambda k: parts[idx[k]].strip() if idx[k] is not None else ""  # noqa: E731
        try:
            nav = float(get("nav").replace(",", ""))
        except ValueError:
            continue  # "N.A." and similar
        d = parse_date(get("date"))
        if d is None or not get("code"):
            continue
        name = " - ".join(p for p in (get("name"), get("plan"), get("option")) if p and p != "-")
        rows.append(NavRow(get("code"), name, nav, d, amc, get("isin1").strip("-"), get("isin2").strip("-")))
    return rows


@dataclass(frozen=True)
class NavQuote:
    code: str
    label: str
    name: str
    nav: float | None
    nav_date: date | None
    prev_nav: float | None = None
    prev_date: date | None = None

    @property
    def change(self) -> float | None:
        if self.nav is None or self.prev_nav is None:
            return None
        return self.nav - self.prev_nav

    @property
    def change_pct(self) -> float | None:
        if self.change is None or not self.prev_nav:
            return None
        return self.change / self.prev_nav * 100

    def line(self) -> str:
        if self.nav is None:
            return f"- {self.label}: no NAV found for scheme code {self.code}"
        text = f"- {self.label}: {self.nav:,.4f} ({self.nav_date:%d %b})"
        if self.change is not None:
            text += f", {self.change:+.4f} ({self.change_pct:+.2f}%) since {self.prev_date:%d %b}"
        return text


class NavService:
    def __init__(self, conn: sqlite3.Connection, cfg: dict[str, Any], fetcher: Fetcher,
                 now: Callable[[], datetime]):
        self.db, self.cfg, self.fetcher, self.now = conn, section(cfg, "nav"), fetcher, now
        self.db.executescript(_SCHEMA)

    # ---- configuration ----

    def schemes(self) -> list[dict[str, str]]:
        out = []
        for s in self.cfg.get("schemes") or []:
            if isinstance(s, dict) and s.get("code"):
                out.append({"code": str(s["code"]).strip(), "label": str(s.get("label") or s["code"])})
            elif isinstance(s, (str, int)):
                out.append({"code": str(s), "label": str(s)})
        return out

    # ---- fetching ----

    def last_fetch(self) -> datetime | None:
        row = self.db.execute("SELECT value FROM india_meta WHERE key='nav_last_fetch'").fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def is_fresh(self) -> bool:
        last = self.last_fetch()
        hours = float(self.cfg.get("refresh_hours") or 12)
        return last is not None and self.now() - last < timedelta(hours=hours)

    def refresh(self, force: bool = False) -> str | None:
        """Fetch the file unless the cache is fresh. Returns an error text, or None."""
        if not force and self.is_fresh():
            return None
        url = str(self.cfg.get("url") or "https://portal.amfiindia.com/spages/NAVAll.txt")
        try:
            rows = parse_nav_all(self.fetcher.get(url).decode("utf-8", errors="replace"))
        except (FetchError, ValueError) as e:
            return f"AMFI NAV file unavailable: {e}"
        self.store(rows)
        return None

    def store(self, rows: list[NavRow]) -> None:
        stamp = self.now().isoformat(timespec="seconds")
        self.db.executemany(
            "INSERT OR REPLACE INTO india_nav_latest (code, name, amc, isin1, isin2, nav, nav_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r.code, r.name, r.amc, r.isin1, r.isin2, r.nav, r.nav_date.isoformat()) for r in rows])
        wanted = {s["code"] for s in self.schemes()}
        self.db.executemany(
            "INSERT OR IGNORE INTO india_nav_history (code, nav_date, nav, fetched_at) VALUES (?, ?, ?, ?)",
            [(r.code, r.nav_date.isoformat(), r.nav, stamp) for r in rows if r.code in wanted])
        self.db.execute("INSERT OR REPLACE INTO india_meta (key, value) VALUES ('nav_last_fetch', ?)", (stamp,))
        self.db.commit()

    # ---- reading ----

    def quote(self, code: str, label: str | None = None) -> NavQuote:
        latest = self.db.execute("SELECT name, nav, nav_date FROM india_nav_latest WHERE code=?", (code,)).fetchone()
        hist = self.db.execute("SELECT nav, nav_date FROM india_nav_history WHERE code=? ORDER BY nav_date DESC LIMIT 2",
                               (code,)).fetchall()
        if not latest and not hist:
            return NavQuote(code, label or code, "", None, None)
        name = latest[0] if latest else ""
        nav, nav_date = (latest[1], date.fromisoformat(latest[2])) if latest else (hist[0][0], date.fromisoformat(hist[0][1]))
        prev = next((h for h in hist if h[1] < nav_date.isoformat()), None)
        return NavQuote(code, label or name or code, name, nav, nav_date,
                        prev[0] if prev else None, date.fromisoformat(prev[1]) if prev else None)

    def quotes(self) -> list[NavQuote]:
        return [self.quote(s["code"], s["label"]) for s in self.schemes()]

    def search(self, query: str, limit: int = 8) -> list[NavQuote]:
        q = query.strip()
        if q.isdigit():
            return [self.quote(q)]
        words = [w for w in q.lower().split() if w]
        if not words:
            return []
        sql = "SELECT code FROM india_nav_latest WHERE " + " AND ".join("lower(name) LIKE ?" for _ in words)
        rows = self.db.execute(sql + " ORDER BY name LIMIT ?", [f"%{w}%" for w in words] + [limit]).fetchall()
        return [self.quote(r[0]) for r in rows]


def format_quotes(quotes: list[NavQuote]) -> str:
    return "\n".join(q.line() for q in quotes)
