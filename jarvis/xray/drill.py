"""Offline x-ray self-checks (PLAN.md 18.1 item 6, the offline part).

No node, Chrome or network: a synthetic fingerprint string must resolve to Three.js r165 and
GSAP 3.12.5, and every line of a synthetic capture digest must name its source. The spoken-address
parser checks live with the voice routes (another module), not here.
"""

from __future__ import annotations

from jarvis.xray.capture import JARVIS, REA, Asset, Capture, Step
from jarvis.xray.fingerprints import Fingerprint, find_in_text

SYNTHETIC_BANNER = (
    "/**\n * @license\n * Copyright 2010-2024 Three.js Authors\n * SPDX-License-Identifier: MIT\n */\n"
    "const REVISION = '165';\n"
    "/*!\n * GSAP 3.12.5\n * https://gsap.com\n * @license Copyright 2008-2024, GreenSock. All rights reserved.\n */\n"
)


def offline_checks() -> list[tuple[str, bool, str]]:
    """[(name, ok, detail)] for `jarvis xray drill` (offline part) and the tests."""
    checks: list[tuple[str, bool, str]] = []

    found = {f.library: f.version for f in find_in_text(SYNTHETIC_BANNER, JARVIS, "synthetic banner")}
    ok = found.get("Three.js") == "r165"
    checks.append(("fingerprint Three.js r165", ok, f"saw {found.get('Three.js')!r}"))
    ok = found.get("GSAP") == "3.12.5"
    checks.append(("fingerprint GSAP 3.12.5", ok, f"saw {found.get('GSAP')!r}"))

    cap = Capture(url="https://example.test/", host="example.test", started_at="2026-01-01T00:00:00+00:00",
                  finished_at="2026-01-01T00:00:30+00:00",
                  steps=[Step("Load page", JARVIS, True, "readyState complete"),
                         Step("REA inspect-web-page", REA, True, "2 fields")],
                  inspect={"title": "Example", "scripts": ["a.js", "b.js"]}, bundle={"modules": 3},
                  assets=[Asset("script", "https://example.test/a.js", 1200)],
                  fingerprints=[Fingerprint("Three.js", "r165", "banner", REA),
                                Fingerprint("GSAP", "3.12.5", "window.gsap.version = 3.12.5", JARVIS)])
    unlabelled = [l for l in cap.digest().splitlines() if l.strip() and not (l.startswith(f"[{REA}] ") or l.startswith(f"[{JARVIS}] "))]
    checks.append(("every digest line names its source", not unlabelled,
                   "all lines labelled" if not unlabelled else f"unlabelled: {unlabelled[:3]}"))

    small = cap.digest(max_chars=300)
    checks.append(("digest respects max_chars", len(small) <= 300 and small.endswith("chars)"),
                   f"{len(small)} chars"))
    return checks
