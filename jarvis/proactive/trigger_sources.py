"""The five trigger sources. Each is a small polling checker: it looks at the world once and
returns every item that currently matches, each with a dedupe key. The engine
(triggers.py) decides what is new, what fires and when.

No source calls a model. Network sources reach the world only through objects passed in
(WebClient, a Google client factory), so tests use fakes.

- file_new        new or changed files in a folder inside the allowed file roots
- web_price       a store page (tier A only; never Amazon/Flipkart) with a price below a limit
- email_from      new Gmail messages from a sender / with a subject word (id, and headers only if allowed)
- calendar_soon   a calendar event that starts within N minutes
- web_search_new  new results (by URL) for a Tavily search
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from jarvis.privacy import allowed, redact_p3


class SourceWaiting(Exception):
    """Not an error: the source cannot be checked right now (not connected, no key, credit limit).
    No backoff; the next check happens at the normal interval."""


class SourceError(Exception):
    """The check failed (network, API). The engine backs off and records it."""


@dataclass
class TriggerEvent:
    key: str                         # dedupe key: the action fires once per key
    summary: str                     # one line for Sachin (notification, CLI); safe to send
    detail: str = ""                 # what the action's prompt gets (safe fields only)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PollContext:
    now: datetime
    home: Path
    roots: list[Path]
    settings: dict[str, Any]                         # the `triggers` section of config/proactive.yaml
    web: Any = None                                  # jarvis.tools.web.WebClient
    tavily_key: Callable[[], str | None] = lambda: None
    google: Callable[[], Any] = lambda: None         # -> GoogleClient | None
    connectors_cfg: dict[str, Any] = field(default_factory=dict)
    credits: "CreditBudget | None" = None
    max_privacy: str = "P1"                          # where action input and notifications may go

    def section(self, source: str) -> dict[str, Any]:
        value = self.settings.get(source) or {}
        return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- Tavily credit budget


class CreditBudget:
    """Tavily credits per day for all triggers together (search basic = 1, extract basic = 1
    per 5 links, extract advanced = 2 per 5 links; docs.tavily.com). Reserved before the call,
    atomically, so two pollers cannot both spend the last credit."""

    def __init__(self, conn: sqlite3.Connection, daily_limit: int, day: str):
        self.db = conn
        self.limit = int(daily_limit)
        self.day = day
        self.db.execute("CREATE TABLE IF NOT EXISTS trig_credits (day TEXT PRIMARY KEY, used INTEGER NOT NULL)")
        self.db.commit()

    def used(self) -> int:
        row = self.db.execute("SELECT used FROM trig_credits WHERE day=?", (self.day,)).fetchone()
        return int(row[0]) if row else 0

    def reserve(self, n: int) -> bool:
        self.db.execute("INSERT OR IGNORE INTO trig_credits (day, used) VALUES (?, 0)", (self.day,))
        cur = self.db.execute("UPDATE trig_credits SET used = used + ? WHERE day=? AND used + ? <= ?",
                              (n, self.day, n, self.limit))
        self.db.commit()
        return cur.rowcount == 1


def _spend(ctx: PollContext, n: int) -> None:
    if ctx.credits is not None and not ctx.credits.reserve(n):
        raise SourceWaiting(f"daily Tavily credit limit for triggers reached ({ctx.credits.limit}); "
                            "checks continue tomorrow")


# ---------------------------------------------------------------- file_new

_PARTIAL = (".part", ".crdownload", ".tmp", ".download", ".partial")


def poll_file_new(cond: dict[str, Any], ctx: PollContext) -> list[TriggerEvent]:
    from jarvis.proactive.trigger_parse import TriggerInvalid, resolve_folder

    try:
        folder = resolve_folder(str(cond.get("folder") or ""), ctx.home, ctx.roots)
    except TriggerInvalid as e:
        raise SourceError(str(e)) from None
    if not folder.exists():
        raise SourceWaiting(f"folder {cond.get('folder')} does not exist yet")
    if not folder.is_dir():
        raise SourceError(f"{cond.get('folder')} is not a folder")
    pattern = str(cond.get("glob") or "*")
    events = []
    items = folder.rglob("*") if cond.get("recursive") else folder.iterdir()
    for path in sorted(items):
        name = path.name
        if not path.is_file() or name.startswith((".", "~$")) or name.lower().endswith(_PARTIAL):
            continue
        if not fnmatch.fnmatch(name.lower(), pattern.lower()):
            continue
        st = path.stat()
        rel = path.relative_to(folder).as_posix()
        shown = f"{cond.get('folder')}/{rel}".replace("//", "/")
        first = ctx.roots[0].expanduser().resolve() if ctx.roots else None
        resolved = path.resolve()
        read_path = resolved.relative_to(first).as_posix() if first and resolved.is_relative_to(first) else str(resolved)
        events.append(TriggerEvent(
            key=f"{rel}|{st.st_mtime_ns}|{st.st_size}",
            summary=f"new or changed file: {shown} ({max(1, st.st_size // 1024)} KB)",
            detail=f"- file: {shown} (path for read_file: {read_path}; {st.st_size} bytes)",
            data={"path": str(path), "shown": shown, "size": st.st_size}))
    return events


# ---------------------------------------------------------------- web_price


def _amount(text: str) -> float:
    return float(re.sub(r"[^0-9.]", "", text) or 0)


def _slug_product(url: str) -> str:
    """Product words from the link, e.g. croma.com/hp-victus-15-ryzen-5/p/301234 -> 'hp victus 15 ryzen 5'."""
    path = urllib.parse.urlparse(url).path
    parts = [p for p in path.split("/") if p and "-" in p]
    return max(parts, key=len).replace("-", " ") if parts else ""


def poll_web_price(cond: dict[str, Any], ctx: PollContext) -> list[TriggerEvent]:
    from jarvis.agents.sources import classify, price_evidence, product_tokens
    from jarvis.proactive.trigger_parse import AMAZON_FLIPKART
    from jarvis.tools.web import WebError

    url = str(cond.get("url") or "")
    tier = classify(url)
    if tier.kind == "user_check":                # checked again at every poll, not only when saved
        raise SourceError(AMAZON_FLIPKART.format(host=tier.match))
    if tier.kind != "store":
        raise SourceError(f"{tier.match} is not an official store page (tier {tier.tier})")
    if ctx.web is None:
        raise SourceWaiting("web access is not available")
    limit = float(cond.get("below") or 0)
    product = str(cond.get("product") or "")
    if not product_tokens(product):
        product = _slug_product(url) or product
    try:
        ctx.web.check_url(url)
    except WebError as e:
        raise SourceError(str(e)) from None

    page, method = "", ""
    key = ctx.tavily_key()
    if key:
        for depth, cost in (("basic", 1), ("advanced", 2)):
            _spend(ctx, cost)
            try:
                res = ctx.web.tavily_extract(key, [url], depth=depth)
            except WebError as e:
                raise SourceError(f"Tavily: {e}") from None
            content = next((r["raw_content"] for r in res["results"] if r["raw_content"].strip()), "")
            if content:
                page, method = content, f"Tavily Extract ({depth})"
                if price_evidence(page, product).ok:
                    break
    if not page:
        try:
            page, method = ctx.web.fetch_text(url), "plain fetch"
        except WebError as e:
            raise SourceError(f"could not read the page: {e}") from None
    ev = price_evidence(page, product)
    if not ev.ok:
        raise SourceError(f"no price found on the page ({ev.reason})")
    # EMI amounts and accessories sit near the product name too: ignore amounts far below the limit.
    floor = limit * float(ctx.section("web_price").get("ignore_below_fraction", 0.3))
    prices = sorted(a for a in (_amount(x) for x in ev.amounts) if a >= floor)
    if not prices:
        raise SourceError("only small amounts (EMI or accessories?) near the product name")
    price = prices[0]
    if price >= limit:
        return []
    host = tier.match
    day = ctx.now.strftime("%Y-%m-%d")
    return [TriggerEvent(
        key=f"below|{price:.0f}",
        summary=f"price Rs {price:,.0f} is below your limit Rs {limit:,.0f} at {host} (checked {day} via {method}; "
                f"confirm on the page before buying): {url}",
        detail=f"- store page price Rs {price:,.0f} (limit Rs {limit:,.0f}), {host}, fetched {day}: {url}",
        data={"price": price, "limit": limit, "url": url})]


# ---------------------------------------------------------------- email_from


def _gmail_query(cond: dict[str, Any], lookback_days: int) -> str:
    parts = []
    if cond.get("sender"):
        parts.append(f"from:{cond['sender']}")
    if cond.get("subject"):
        subject = str(cond["subject"]).replace('"', "")
        parts.append(f'subject:"{subject}"' if " " in subject else f"subject:{subject}")
    parts.append(f"newer_than:{max(1, lookback_days)}d")
    return " ".join(parts)


def headers_allowed(ctx: PollContext) -> bool:
    """Sender and subject follow gmail.header_class (open decision #19, P2 by default)."""
    header_class = str((ctx.connectors_cfg.get("gmail") or {}).get("header_class") or "P2")
    return allowed(header_class, ctx.max_privacy)


def poll_email_from(cond: dict[str, Any], ctx: PollContext) -> list[TriggerEvent]:
    from jarvis.connectors.google.client import GoogleError

    client = ctx.google()
    if client is None:
        raise SourceWaiting("Google is not connected (jarvis google auth)")
    sec = ctx.section("email_from")
    try:
        msgs = client.search_messages(_gmail_query(cond, int(sec.get("lookback_days", 2))),
                                      int(sec.get("max_results", 20)))
    except GoogleError as e:
        raise SourceError(f"Gmail: {e}") from None
    sender = str(cond.get("sender") or "").lower()
    subject = str(cond.get("subject") or "").lower()
    show_headers = headers_allowed(ctx)
    events = []
    for m in msgs:
        # Checked here too: the Gmail query is a filter we trust, but not blindly.
        if sender and sender not in str(m.get("from", "")).lower():
            continue
        if subject and subject not in str(m.get("subject", "")).lower():
            continue
        mid = str(m.get("id", ""))
        if not mid:
            continue
        # Only id, sender and subject ever leave this function; body and snippet are P2 and dropped.
        if show_headers:
            frm, _ = redact_p3(str(m.get("from", ""))[:120])
            subj, _ = redact_p3(str(m.get("subject", ""))[:160])
            summary = f"new email from {frm}: {subj} (id {mid})"
            detail = f"- email id {mid}, from: {frm}, subject: {subj}"
            data = {"id": mid, "from": frm, "subject": subj}
        else:
            summary = f"a new email matched your rule (id {mid}); sender and subject withheld (private)"
            detail = f"- email id {mid} (sender and subject withheld: private; the text is never passed on)"
            data = {"id": mid}
        events.append(TriggerEvent(key=f"msg|{mid}", summary=summary, detail=detail, data=data))
    return events


# ---------------------------------------------------------------- calendar_soon


def poll_calendar_soon(cond: dict[str, Any], ctx: PollContext) -> list[TriggerEvent]:
    from jarvis.connectors.google.client import GoogleError

    client = ctx.google()
    if client is None:
        raise SourceWaiting("Google is not connected (jarvis google auth)")
    minutes = int(cond.get("minutes") or 15)
    cal = str((ctx.connectors_cfg.get("google") or {}).get("calendar_id") or "primary")
    try:
        items = client.list_events(cal, ctx.now, ctx.now + timedelta(minutes=minutes), max_results=20)
    except GoogleError as e:
        raise SourceError(f"Calendar: {e}") from None
    title_word = str(cond.get("title") or "").lower()
    events = []
    for e in items:
        start_raw = (e.get("start") or {}).get("dateTime")
        if not start_raw:
            continue  # all-day events have no start time to warn about
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        title = str(e.get("summary") or "(no title)")      # titles and times are P1 (schedule outlines)
        if title_word and title_word not in title.lower():
            continue
        if start < ctx.now:
            continue
        left = int((start - ctx.now).total_seconds() // 60)
        when = start.astimezone(ctx.now.tzinfo).strftime("%H:%M")
        events.append(TriggerEvent(
            key=f"evt|{e.get('id', title)}|{start_raw}",
            summary=f"'{title}' starts at {when} (in {left} min)",
            detail=f"- calendar event '{title}' at {when}, in {left} minutes",
            data={"id": e.get("id"), "title": title, "start": start_raw}))
    return events


# ---------------------------------------------------------------- web_search_new


def _norm_url(url: str) -> str:
    p = urllib.parse.urlparse(url.strip())
    query = "&".join(q for q in p.query.split("&") if q and not q.lower().startswith(("utm_", "ref=", "fbclid")))
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}" + (f"?{query}" if query else "")


def poll_web_search_new(cond: dict[str, Any], ctx: PollContext) -> list[TriggerEvent]:
    from jarvis.tools.web import WebError

    key = ctx.tavily_key()
    if not key:
        raise SourceWaiting("the Tavily key is missing (jarvis secret set tavily_api_key)")
    if ctx.web is None:
        raise SourceWaiting("web access is not available")
    sec = ctx.section("web_search_new")
    _spend(ctx, 1)
    try:
        results = ctx.web.tavily_search(key, str(cond.get("query")), topic=str(cond.get("topic") or "general"),
                                        max_results=int(sec.get("max_results", 5)))
    except WebError as e:
        raise SourceError(f"Tavily: {e}") from None
    events = []
    for r in results:
        url = str(r.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        # Page titles are outside text: shortened, P3-redacted, and given to the action as data only.
        title, _ = redact_p3(" ".join(str(r.get("title") or "").split())[:120])
        events.append(TriggerEvent(key=f"url|{_norm_url(url)}", summary=f"{title}: {url}",
                                   detail=f"- result: {title} | {url}", data={"url": url, "title": title}))
    return events


@dataclass(frozen=True)
class SourceSpec:
    kind: str
    poll: Callable[[dict[str, Any], PollContext], list[TriggerEvent]]
    baseline: bool          # first check only notes what exists; later checks fire on new items
    taints: bool            # outside content reaches the action: only read-only tools run in it
    every_key: str          # which setting gives the default check interval


SOURCES: dict[str, SourceSpec] = {
    "file_new": SourceSpec("file_new", poll_file_new, True, False, "every_minutes"),
    "web_price": SourceSpec("web_price", poll_web_price, False, True, "every_hours"),
    "email_from": SourceSpec("email_from", poll_email_from, True, True, "every_minutes"),
    "calendar_soon": SourceSpec("calendar_soon", poll_calendar_soon, False, False, "every_minutes"),
    "web_search_new": SourceSpec("web_search_new", poll_web_search_new, True, True, "every_hours"),
}
