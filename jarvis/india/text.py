"""Indian text helpers: Devanagari digits, rupee amounts, dates, Aadhaar/PAN masking.

Deterministic and local: these run on mail bodies and SMS text, which never go to a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from jarvis import privacy

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def ascii_digits(text: str) -> str:
    return text.translate(_DEV_DIGITS)


# ---------------------------------------------------------------- masking

# Reuse the privacy gate's patterns (one definition of what an Aadhaar or PAN looks like).
_PATTERNS = dict(privacy._P3_PATTERNS)  # noqa: SLF001 - shared on purpose
AADHAAR = _PATTERNS["aadhaar"]
PAN = re.compile(_PATTERNS["pan"].pattern, re.IGNORECASE)  # PAN typed in lower case is still a PAN


def mask_tail(value: str, keep: int = 4) -> str:
    """Keep only the last `keep` letters/digits: 'XXXX1234'. Short values stay as they are."""
    chars = re.sub(r"[^0-9A-Za-z]", "", ascii_digits(value or ""))
    if len(chars) <= keep:
        return chars
    return "X" * 4 + chars[-keep:].upper()


def mask_ids(text: str) -> tuple[str, list[str]]:
    """Replace full Aadhaar and PAN numbers with their masked form. Returns (text, kinds found)."""
    text = ascii_digits(text or "")
    kinds: list[str] = []

    def aadhaar(m: re.Match[str]) -> str:
        kinds.append("aadhaar")
        return "XXXX XXXX " + re.sub(r"\D", "", m.group())[-4:]

    def pan(m: re.Match[str]) -> str:
        kinds.append("pan")
        return "XXXXXX" + m.group()[-4:].upper()

    text = AADHAAR.sub(aadhaar, text)
    text = PAN.sub(pan, text)
    return text, kinds


def scrub(text: str) -> str:
    """Mask Aadhaar/PAN, then withhold other secrets (OTPs, card numbers, keys)."""
    masked, _ = mask_ids(text)
    return privacy.redact_p3(masked)[0]


# ---------------------------------------------------------------- amounts

_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_CUR_BEFORE = re.compile(r"(?:₹|\bRs\.?|\bINR|\bरु\.?|रू\.?)\s*" + _NUM, re.IGNORECASE)
_CUR_AFTER = re.compile(_NUM + r"\s*(?:/-|रुपये|रु\.|\brupees\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Amount:
    paise: int
    start: int

    @property
    def rupees(self) -> float:
        return self.paise / 100


def _paise(raw: str) -> int:
    raw = raw.replace(",", "")
    whole, _, frac = raw.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2]) if whole else 0


def find_amounts(text: str) -> list[Amount]:
    text = ascii_digits(text)
    found: dict[int, Amount] = {}
    for pat in (_CUR_BEFORE, _CUR_AFTER):
        for m in pat.finditer(text):
            value = _paise(m.group(1))
            if value > 0:
                found.setdefault(m.start(), Amount(value, m.start()))
    return sorted(found.values(), key=lambda a: a.start)


def format_inr(paise: int | None) -> str:
    """Indian grouping: 1,23,456.50 -> 'Rs 1,23,456.50'."""
    if paise is None:
        return "Rs ?"
    rupees, p = divmod(int(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"Rs {s}" + (f".{p:02d}" if p else "")


# ---------------------------------------------------------------- dates

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    "जानेवारी": 1, "फेब्रुवारी": 2, "मार्च": 3, "एप्रिल": 4, "मे": 5, "जून": 6, "जुलै": 7, "ऑगस्ट": 8,
    "सप्टेंबर": 9, "ऑक्टोबर": 10, "नोव्हेंबर": 11, "डिसेंबर": 12,
}
_MON = "|".join(sorted((re.escape(k) for k in MONTHS), key=len, reverse=True))
_DATE_PATTERNS = [
    ("ymd", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")),
    ("d_mon_y", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]*(" + _MON + r")\.?[\s\-,]*(\d{4}|\d{2})\b",
                           re.IGNORECASE)),
    ("mon_d_y", re.compile(r"\b(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class FoundDate:
    value: date
    start: int


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def find_dates(text: str) -> list[FoundDate]:
    """Every date in the text, in reading order. Numeric dates are day-first (Indian usage)."""
    text = ascii_digits(text)
    found: dict[int, FoundDate] = {}
    taken: list[tuple[int, int]] = []
    for kind, pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            g = m.groups()
            try:
                if kind == "ymd":
                    d = date(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "dmy":
                    d = date(_year(g[2]), int(g[1]), int(g[0]))
                elif kind == "d_mon_y":
                    d = date(_year(g[2]), MONTHS[g[1].lower()], int(g[0]))
                else:
                    d = date(int(g[2]), MONTHS[g[0].lower()], int(g[1]))
            except (ValueError, KeyError):
                continue
            found[m.start()] = FoundDate(d, m.start())
            taken.append((m.start(), m.end()))
    return sorted(found.values(), key=lambda f: f.start)


def parse_date(text: str) -> date | None:
    dates = find_dates(text or "")
    return dates[0].value if dates else None
