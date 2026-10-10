"""Phase 3 done-when (part 2): a demonstrated task replays as a skill.

Opt-in: JARVIS_LIVE=1 pytest -m live -s tests/test_skill_live.py
Demo in chat -> stop recording -> model drafts SKILL.md -> approve -> a NEW session runs
the skill with a different input -> the result is checked on disk.
"""

import os
from datetime import datetime

import pytest

pytestmark = pytest.mark.live


def test_demo_replays_as_skill(isolated):
    if os.environ.get("JARVIS_LIVE") != "1":
        pytest.skip("set JARVIS_LIVE=1 to call the real provider")
    from jarvis.cli_tasks import recorder
    from jarvis.core.runtime import make_chat, open_runtime
    from jarvis.providers import make_provider
    from jarvis.routing.policy import decide

    rt = open_runtime()
    ws = rt.paths.home / "workspace"
    try:
        rec = recorder(rt)
        r = rec.start("weekly plan note")
        s = make_chat(rt, approver=lambda req: req.tier in ("T1", "T2"))
        s.now = lambda: datetime(2026, 10, 12, 9, 0)
        print("demo:", s.send("Create my weekly plan file for the week of 2026-10-12: notes/week-2026-10-12.md "
                              "with the headings Goals, Meetings and Reading, and under Goals write 'gym 4 times'."))
        rec.note("Every Monday I make a weekly plan file like this; the date changes, the headings stay.")
        _, evidence = rec.stop()
        assert "write_file" in evidence

        d = decide(rt.config, "skill_draft")
        tiers = {t.spec.name: t.tier for t in s.tools.all()}
        draft = rec.draft(r.id, make_provider(d.provider, rt.config), d, tiers)
        print(draft.read_text(encoding="utf-8"))
        skill = rec.approve(r.id, rt.paths.home / "skills")
        name = skill.parent.name

        s2 = make_chat(rt, approver=lambda req: req.tier in ("T1", "T2"))
        s2.now = lambda: datetime(2026, 10, 19, 9, 0)
        reply = s2.send(f"Run the skill {name} for the week of 2026-10-19.")
        print("replay:", reply)
        out = ws / "notes" / "week-2026-10-19.md"
        assert out.exists(), list((ws / "notes").glob("*"))
        text = out.read_text(encoding="utf-8").lower()
        assert all(h in text for h in ("goals", "meetings", "reading"))
        used = [r[0] for r in rt.store.conn.execute("SELECT tool FROM tool_runs WHERE ok=1 ORDER BY id")]
        assert "load_skill" in used
    finally:
        rt.close()
