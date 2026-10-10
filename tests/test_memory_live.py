"""Phase 1 done-when: teach 10 facts; in a new session at least 9 are used correctly.
Includes "act" probes (behaviour follows a memory without the prompt mentioning it).

Synthetic facts only (public repo). Opt-in: JARVIS_LIVE=1 pytest -m live -s
Uses the approved routes (main chat on Opus, memory enrichment on Haiku).
"""

import os
import re
from datetime import datetime

import pytest

pytestmark = pytest.mark.live

# (teach, probe, check) -- check: ("any", [...]) | ("avoid", word) | ("bullets", n)
CASES = [
    ("My demo laptop's name is Falcon", "What is my laptop called?", ("any", ["falcon"])),
    ("maza gym roj sakali 6 vajta asto", "When do I go to the gym?", ("any", ["6"])),
    ("माझ्या मुलीचं नाव मीरा आहे", "What is my daughter's name?", ("any", ["मीरा", "meera", "mira"])),
    ("I keep my passport photocopies in the blue folder", "Where are my passport copies kept?", ("any", ["blue"])),
    ("orbit project ~/Projects/orbit madhe ahe, npm start ne chalto", "orbit project kasa chalvaycha?", ("any", ["npm start"])),
    ("I never eat mushrooms", "Suggest one pizza topping for me tonight, in one line.", ("avoid", "mushroom")),
    ("My bike is a red Pulsar", "What colour is my bike?", ("any", ["red", "लाल", "lal"])),
    ("Always reply to me in short bullet points", "Give me 3 tips for better sleep.", ("bullets", 3)),
    ("My office wifi network is called DemoNet-5G", "What's the office wifi network name?", ("any", ["demonet"])),
    ("maza favourite cricketer Rahul Dravid ahe", "Who is my favourite cricketer?", ("any", ["dravid", "द्रविड"])),
]


def _passes(reply: str, check) -> bool:
    kind, arg = check
    low = reply.lower()
    if kind == "any":
        return any(s.lower() in low for s in arg)
    if kind == "avoid":
        # The word may appear only when negated ("no mushrooms", "without mushroom").
        for m in re.finditer(arg, low):
            if not re.search(r"\b(no|not|without|skip|avoid|never)\b", low[max(0, m.start() - 25):m.start()]):
                return False
        return bool(reply.strip())
    bullets = [l for l in reply.splitlines() if re.match(r"^\s*([-*•]|\d+[.)])\s+", l)]
    return len(bullets) >= arg


def test_teach_ten_facts_then_use_them(isolated):
    if os.environ.get("JARVIS_LIVE") != "1":
        pytest.skip("set JARVIS_LIVE=1 to call the real provider")
    from jarvis.core.runtime import make_chat, make_extractor, open_runtime

    rt = open_runtime()
    try:
        extractor = make_extractor(rt)
        for teach, _, _ in CASES:
            extractor.remember(teach)

        results = []
        for teach, probe, check in CASES:
            session = make_chat(rt)  # a new session for every probe: nothing from teaching is in history
            session.now = lambda: datetime(2026, 10, 10, 11, 0)
            reply = session.send(probe)
            ok = _passes(reply, check)
            results.append(ok)
            print(f"\n{'PASS' if ok else 'FAIL'} | {probe}\n  -> {reply[:300]}")
        print(f"\nMemory test: {sum(results)}/10")
        assert sum(results) >= 9
    finally:
        rt.close()
