"""Privacy gate v1 (PLAN.md 5.9): P0-P3 classes and deterministic P3 filters.

P3 (secrets) is never stored and never sent anywhere. The gate runs in the core,
before any provider adapter sees a payload.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CLASSES = ("P0", "P1", "P2", "P3")
SENSITIVITY_TO_CLASS = {"public": "P0", "normal": "P1", "sensitive": "P2", "secret": "P3"}

_P3_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9_\-]{8,})")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("password", re.compile(r"(?i)\b(password|passwd|pwd|पासवर्ड)\s*(is|=|:|आहे)\s*\S+")),
    ("otp", re.compile(r"(?i)\b(otp|one[- ]time (pass)?code|verification code)\b\D{0,15}\d{4,8}\b")),
    # 12 digits, not part of a longer number (e.g. a card number).
    ("aadhaar", re.compile(r"(?<![\d-])(?<!\d )\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b(?![ -]?\d)")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def ascii_digits(text: str) -> str:
    """Devanagari (and other) decimal digits as ASCII digits, one character for one, so the
    P3 patterns see "२३४५ ६७८९ ०१२३" as an Aadhaar number. Positions stay the same."""
    return "".join(str(unicodedata.decimal(ch)) if not ch.isascii() and ch.isdecimal() else ch for ch in text)


def find_p3(text: str) -> list[str]:
    """Kinds of secret found in text (empty list if none)."""
    text = ascii_digits(text)
    kinds = [kind for kind, pat in _P3_PATTERNS if pat.search(text)]
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            kinds.append("card_number")
            break
    return kinds


def redact_p3(text: str) -> tuple[str, int]:
    """Replace secrets with [WITHHELD]. Returns (text, number of replacements).

    Matching runs on a copy with ASCII digits (so Devanagari digits are caught too); the
    replacements are applied at the same positions of the original, which is otherwise kept."""
    norm, count = ascii_digits(text), 0

    def cut(spans: list[tuple[int, int]]) -> None:
        nonlocal text, norm, count
        for start, end in reversed(spans):
            text = text[:start] + "[WITHHELD]" + text[end:]
            norm = norm[:start] + "[WITHHELD]" + norm[end:]
        count += len(spans)

    for _, pat in _P3_PATTERNS:
        cut([m.span() for m in pat.finditer(norm)])

    def is_card(m: re.Match[str]) -> bool:
        digits = re.sub(r"\D", "", m.group())
        return 13 <= len(digits) <= 19 and _luhn_ok(digits)

    cut([m.span() for m in _CARD.finditer(norm) if is_card(m)])
    return text, count


def allowed(item_class: str, max_class: str) -> bool:
    """P3 is never allowed. Otherwise the item must not exceed the route's limit."""
    if item_class == "P3":
        return False
    return CLASSES.index(item_class) <= CLASSES.index(max_class)


@dataclass
class GateReport:
    withheld: int = 0
    redacted: int = 0
    classes: set[str] | None = None
