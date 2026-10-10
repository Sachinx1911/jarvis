"""Source tiers for prices and shop facts. Deterministic: no model involved.

Tier A - official retailer or brand store page (croma.com, dell.com/en-in, ...). A price read
         there by web_extract, with a Rs amount near the product name, is "confirmed" for
         the day it was fetched (prices are valid for the same day only).
         Amazon.in and Flipkart are retailers too, but their terms forbid automated price
         collection: Jarvis never fetches them, it only gives their links for the user to
         check ("check yourself").
Tier B - aggregators and price comparison (Smartprix, 91mobiles, ...): "estimate".
Tier C - blogs, news and everything else: not a price source.

Domain lists live in config/sources.yaml (overrides: config/local.yaml, key sources_file).
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from jarvis.paths import CONFIG_DIR

URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")

# Labels the writer must put on every report row that shows a price.
LABEL_CONFIRMED = "confirmed"
LABEL_ESTIMATE = "estimate"
LABEL_CHECK = "check yourself"

# First line of every web_extract result, written by Jarvis (not by the page). Parsed by the
# orchestrator with an anchored match, so text from the page cannot fake it.
HEADER_PREFIX = "JARVIS SOURCE CHECK"
HEADER_RE = re.compile(r"^JARVIS SOURCE CHECK \| price evidence: (FOUND|NONE|NOT CHECKED) \| "
                       r"fetched (\d{4}-\d{2}-\d{2}) \d{2}:\d{2} \| tier ([ABC]) ")

INR_RE = re.compile(r"(?:₹|\bRs\.?|\bINR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
_STOPWORDS = {"the", "and", "with", "for", "laptop", "notebook", "new", "inch", "in", "of", "a"}
NEAR_CHARS = 600


@dataclass(frozen=True)
class SourceTier:
    tier: str    # "A" | "B" | "C"
    kind: str    # "store" | "user_check" | "aggregator" | "other"
    match: str   # the config entry that matched, or the host

    @property
    def describe(self) -> str:
        return {"store": "official store page", "user_check": "Amazon/Flipkart: link for the user to check, never fetched",
                "aggregator": "aggregator: estimate only", "other": "not a price source"}[self.kind]


@dataclass(frozen=True)
class SourceLists:
    user_check: tuple[str, ...] = ()
    store: tuple[str, ...] = ()
    aggregator: tuple[str, ...] = ()


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_lists(config_dir: Path = CONFIG_DIR) -> SourceLists:
    base = _read(config_dir / "sources.yaml")
    local = _read(config_dir / "local.yaml").get("sources_file") or {}
    merged = {k: list(base.get(k) or []) + [x for x in (local.get(k) or []) if x not in (base.get(k) or [])]
              for k in ("user_check", "store", "aggregator")}
    clean = {k: tuple(str(x).strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
                      .rstrip("/") for x in v if str(x).strip()) for k, v in merged.items()}
    return SourceLists(**clean)


@lru_cache(maxsize=1)
def default_lists() -> SourceLists:
    return load_lists()


def _matches(host: str, path: str, entry: str) -> bool:
    domain, _, prefix = entry.partition("/")
    if host != domain and not host.endswith("." + domain):
        return False
    if not prefix:
        return True
    p = path.lower().strip("/")
    return p == prefix or p.startswith(prefix + "/")


def classify(url: str, lists: SourceLists | None = None) -> SourceTier:
    lists = lists or default_lists()
    parsed = urllib.parse.urlparse(url.strip() if "://" in url else "https://" + url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    for kind, tier, entries in (("user_check", "A", lists.user_check), ("store", "A", lists.store),
                                ("aggregator", "B", lists.aggregator)):
        for entry in entries:
            if _matches(host, parsed.path, entry):
                return SourceTier(tier, kind, entry)
    return SourceTier("C", "other", host)


# ---- price evidence on an extracted page ----

@dataclass(frozen=True)
class PriceEvidence:
    ok: bool
    amounts: tuple[str, ...] = ()   # e.g. "Rs 74,990", near the product name
    reason: str = ""
    positions: tuple[int, ...] = field(default=(), compare=False)


_RANGE_BEFORE = re.compile(r"(?:below|under|above|upto|up to|less than|more than|between)\s*$|"
                           r"(?:₹|\brs\.?|\binr)\s*[0-9][0-9,]*\s*(?:-|–|to|and)\s*$", re.IGNORECASE)
_RANGE_AFTER = re.compile(r"^\s*(?:-|–|to|and)\s*(?:₹|rs\.?|inr)?\s*[0-9]", re.IGNORECASE)


def _blank_urls(text: str) -> str:
    """Replace links with spaces (same length, so positions stay): product slugs in menu links
    must not count as the product name being near an amount."""
    return URL_RE.sub(lambda m: " " * len(m.group(0)), text)


def find_inr_amounts(text: str, skip_ranges: bool = False) -> list[tuple[int, str]]:
    """Rs/INR/₹ amounts with their positions. skip_ranges drops price-filter values such as
    "Below Rs 10,000" or "Rs 10,001 to Rs 20,000" (menus, not prices)."""
    out = []
    for m in INR_RE.finditer(text):
        if skip_ranges and (_RANGE_BEFORE.search(text[max(0, m.start() - 30): m.start()])
                            or _RANGE_AFTER.match(text[m.end(): m.end() + 20])):
            continue
        digits = m.group(1).rstrip(",.")
        value = digits.replace(",", "")
        try:
            if float(value) <= 0:
                continue
        except ValueError:
            continue
        out.append((m.start(), f"Rs {digits}"))
    return out


def product_tokens(product: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", product.lower()) if len(t) >= 2 and t not in _STOPWORDS]


def price_evidence(text: str, product: str) -> PriceEvidence:
    """A page is price evidence only if a Rs/INR/₹ amount appears near the product name.

    "Near" = most of the product name's words (60%, at least one) occur within NEAR_CHARS
    characters of the amount. Pages with only menus and filters fail this check.
    """
    text = _blank_urls(text)
    if not find_inr_amounts(text):
        return PriceEvidence(False, reason="no Rs/INR/₹ amount on the page")
    amounts = find_inr_amounts(text, skip_ranges=True)
    if not amounts:
        return PriceEvidence(False, reason="only price-filter ranges on the page, no product price")
    tokens = product_tokens(product)
    if not tokens:
        return PriceEvidence(False, reason="no product name given to check against")
    need = max(1, math.ceil(0.6 * len(tokens)))
    low = text.lower()
    hits: list[tuple[int, str]] = []
    for pos, amount in amounts:
        window = low[max(0, pos - NEAR_CHARS): pos + NEAR_CHARS]
        words = set(re.findall(r"[a-z0-9]+", window))
        if sum(1 for t in tokens if t in words) >= need:
            hits.append((pos, amount))
    if not hits:
        return PriceEvidence(False, reason=f"Rs amounts found, but none near '{product}'")
    seen: list[str] = []
    for _, a in hits:
        if a not in seen:
            seen.append(a)
    return PriceEvidence(True, tuple(seen[:3]), "Rs amount near the product name",
                         tuple(p for p, _ in hits))


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def source_header(url: str, tier: SourceTier, fetched: datetime, method: str, evidence: PriceEvidence | None) -> str:
    if evidence is None:
        status, detail = "NOT CHECKED", "no product name given"
    elif evidence.ok:
        status, detail = "FOUND", ", ".join(evidence.amounts)
        if tier.kind != "store":
            detail += " (not a store page: estimate only)"
    else:
        status, detail = "NONE", evidence.reason
    return (f"{HEADER_PREFIX} | price evidence: {status} | fetched {fetched.strftime('%Y-%m-%d %H:%M')} | "
            f"tier {tier.tier} ({tier.describe}) | via {method} | {detail} | valid for this day only | url: {url}")


def parse_header(result: str) -> tuple[str, str, str] | None:
    """(evidence status, fetch date, tier) from a web_extract result, or None."""
    m = HEADER_RE.match(result or "")
    return (m.group(1), m.group(2), m.group(3)) if m else None


# ---- report check ----

PRICE_RULES = (
    "PRICE RULES (Jarvis checks these automatically):\n"
    "- Every report row that shows a price must carry one of these labels:\n"
    "  * \"confirmed (store page, YYYY-MM-DD)\": only for a price read with web_extract on an official store page "
    "(Croma, Reliance Digital, Vijay Sales, or the brand's India store) where Jarvis found a Rs amount near the product "
    "name, on the same day. The row must contain that store link and the fetch date.\n"
    "  * \"estimate (aggregator)\": a price from Smartprix, 91mobiles, PriceHistory, BuyHatke or similar. The row needs "
    "the aggregator link AND a link for the user to check (an Amazon.in/Flipkart product link marked \"check yourself\", "
    "or a store page).\n"
    "  * \"check yourself (Amazon/Flipkart link)\": Amazon.in and Flipkart prices are never fetched or confirmed by "
    "Jarvis (their terms forbid automated price collection); give the link for the user to check.\n"
    "- A row passes with a confirmed price, or with a labelled estimate plus a user-check link. Presenting an "
    "aggregator, Amazon, Flipkart, blog or news price as confirmed fails.\n"
    "- Blogs, news and reviews are not price sources. Prices are valid for the same day only."
)


def is_price_task(goal: str, plan: dict[str, Any] | None = None) -> bool:
    flag = (plan or {}).get("price_check")
    if isinstance(flag, bool):
        return flag
    return bool(re.search(r"₹|\brs\.?\s*[0-9]|\binr\b|\bprices?\b|\bcosts?\b|\bbudget\b|\bbuy\b", goal, re.IGNORECASE))


def _norm(url: str) -> str:
    return url.split("#")[0].rstrip(".,;").rstrip("/").lower()


def evidence_from_runs(rows: Iterable[tuple[str | None, str | None]]) -> dict[str, tuple[str, str]]:
    """web_extract tool runs (arguments JSON, result) -> {normalized url: (status, fetch date)}."""
    out: dict[str, tuple[str, str]] = {}
    for args, result in rows:
        parsed = parse_header(result or "")
        if not parsed:
            continue
        try:
            url = json.loads(args or "{}").get("url", "")
        except json.JSONDecodeError:
            continue
        if not url:
            continue
        status, date, _ = parsed
        key = _norm(url)
        if status == "FOUND" or key not in out:  # a later FOUND beats an earlier NONE
            out[key] = (status, date)
    return out


def _has_label(line: str, label: str) -> bool:
    low = line.lower()
    if label == LABEL_CONFIRMED:
        return bool(re.search(r"(?<!not )(?<!un)\bconfirmed\b", low))
    return label in low


def check_price_rows(report: str, evidence: dict[str, tuple[str, str]], day: str | None = None,
                     lists: SourceLists | None = None) -> tuple[list[str], int]:
    """Check every report line that shows a Rs amount and a link. Returns (problems, rows checked)."""
    day = day or today()
    problems: list[str] = []
    rows = 0
    for line in report.splitlines():
        urls = [u.rstrip(".,;") for u in URL_RE.findall(line)]
        if not urls or not find_inr_amounts(line):
            continue
        rows += 1
        snippet = " ".join(URL_RE.sub("<link>", line).split())[:90]
        kinds = {u: classify(u, lists).kind for u in urls}
        stores = [u for u, k in kinds.items() if k == "store"]
        aggs = [u for u, k in kinds.items() if k == "aggregator"]
        checks = [u for u, k in kinds.items() if k in ("user_check", "store")]
        if _has_label(line, LABEL_CONFIRMED):
            if not stores:
                problems.append(f"row '{snippet}' says confirmed but has no official store-page link "
                                "(aggregator, Amazon, Flipkart, blog and news prices are never confirmed)")
                continue
            fetched = [evidence.get(_norm(u)) for u in stores]
            found = [e for e in fetched if e and e[0] == "FOUND"]
            if not found:
                problems.append(f"row '{snippet}' says confirmed, but Jarvis never found a Rs price near the product "
                                "on that store page with web_extract; label it an estimate or re-check the store page")
            elif not any(e[1] == day for e in found):
                problems.append(f"row '{snippet}': the confirmed store price was fetched on {found[0][1]}, not today "
                                f"({day}); prices are valid for the same day only")
            elif not any(e[1] in line for e in found):
                problems.append(f"row '{snippet}': a confirmed price must show the store fetch date ({found[0][1]})")
            continue
        if _has_label(line, LABEL_ESTIMATE):
            if not (aggs or stores):
                problems.append(f"row '{snippet}' is an estimate without an aggregator or store link as its source")
            elif not checks:
                problems.append(f"row '{snippet}' is an estimate without a link for the user to check "
                                "(Amazon.in/Flipkart product link or a store page)")
            continue
        if _has_label(line, LABEL_CHECK):
            problems.append(f"row '{snippet}' shows a price with only 'check yourself'; label the price "
                            "'estimate (aggregator)' with its source, or confirm it on a store page")
            continue
        problems.append(f"row '{snippet}' shows a price without a label: use 'confirmed (store page, date)', "
                        "'estimate (aggregator)' or 'check yourself (Amazon/Flipkart link)'")
    return problems, rows
