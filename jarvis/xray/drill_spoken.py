"""Offline drill checks for spoken addresses (PLAN.md 18.1 item 6). `jarvis xray drill` merges these
with the fingerprint checks in jarvis/xray/drill.py. No network, no model, no Chrome."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.xray.spoken import parse_spoken_address, teardown_intent


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


SPOKEN_ADDRESSES = (
    ("igloo dot inc", "https://igloo.inc"),
    ("stripe dot com slash pricing", "https://stripe.com/pricing"),
    ("localhost colon three thousand", "http://localhost:3000"),
    ("igloo.inc", "https://igloo.inc"),
    ("localhost कोलन ३०००", "http://localhost:3000"),
)

INTENTS = (
    ("reverse engineer igloo dot inc", "https://igloo.inc"),
    ("how does this site do that", "this site"),
    ("igloo dot inc चं teardown कर", "https://igloo.inc"),
    ("what time is it", None),
)


def offline_checks() -> list[Check]:
    out: list[Check] = []
    for said, want in SPOKEN_ADDRESSES:
        got = parse_spoken_address(said)
        out.append(Check(f"spoken address: {said}", got == want, f"got {got!r}, want {want!r}"))
    for said, want in INTENTS:
        hit = teardown_intent(said)
        got = hit[0] if hit else None
        ok = (hit is None) if want is None else (hit is not None and got == want)
        out.append(Check(f"teardown intent: {said}", ok, f"got {got!r}, want {want!r}"))
    return out
