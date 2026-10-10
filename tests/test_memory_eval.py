"""The memory eval: fixtures are well formed, the offline metric runs without a model,
and every retrieval change is measured (research 2026-10-10, topic 4)."""

import io
from types import SimpleNamespace

from jarvis.evals import memory_eval as me

CATEGORIES = {"single-fact", "preference", "knowledge-update", "multi-session", "temporal", "unanswerable"}


def test_fixtures_cover_every_category_and_cross_script():
    cases = me.load_cases()
    mem_ids = {m["id"] for m in cases["memories"]}
    session_ids = {s["id"] for s in cases["sessions"]}
    qs = cases["questions"]
    assert {q["category"] for q in qs} == CATEGORIES
    assert {q["script"] for q in qs} == {"en", "roman", "dev"}
    for q in qs:
        for group in q.get("evidence") or []:
            assert group and set(group) <= mem_ids | session_ids, q["id"]
        assert set(q.get("stale") or []) <= mem_ids | session_ids
        if q["category"] == "unanswerable":
            assert not q.get("evidence")
    for m in cases["memories"]:
        assert m.get("session") in session_ids


def test_offline_ablation_measures_each_change():
    steps = {s.name: s for s in me.run_offline()}
    base, full = steps[me.STEPS[0][0]], steps[me.STEPS[-1][0]]
    assert len(full.questions) == len(me.load_cases()["questions"])
    assert full.recall() >= 0.9 > base.recall()
    assert full.recall("temporal") == 1.0 and full.stale_rate() == 0.0
    # each change is visible on its own when it is left out
    assert steps["all - script_forms"].recall() < full.recall()
    assert steps["all - time_aware"].recall("temporal") < full.recall("temporal")
    assert steps["all - session_facts"].session_recall() < full.session_recall()
    assert steps["all - excerpts"].session_recall() == 0
    # cumulative steps never lose recall
    recalls = [steps[name].recall() for name, _ in me.STEPS]
    assert recalls == sorted(recalls)


def test_format_and_cli_offline():
    out = io.StringIO()
    assert me.run_cli(SimpleNamespace(live=False, category="temporal", provider=None), out) == 0
    text = out.getvalue()
    assert "Recall@5" in text and "+ session facts (3) = all" in text


def test_check_answer_rules():
    q = {"category": "knowledge-update", "answer": {"contains_any": ["Baner"], "not_contains": ["Hinjewadi"]},
         "stale_values": ["Hinjewadi"]}
    assert me.check_answer(q, "Your office is in Baner, sir.") == (True, False, "ok")
    ok, stale, _ = me.check_answer(q, "It moved from Hinjewadi to Baner.")
    assert not ok and stale
    un = {"category": "unanswerable"}
    assert me.check_answer(un, "I don't know, sir.")[0]
    assert me.check_answer(un, "मला माहित नाही, sir.")[0]
    assert not me.check_answer(un, "It is 42.")[0]


def test_live_run_uses_the_chat_route_with_a_fake_provider(tmp_path, monkeypatch):
    from jarvis.config import load_config
    from jarvis.providers.fake import FakeProvider

    monkeypatch.setattr("jarvis.providers.make_provider", lambda name, config: FakeProvider(script=["Baner, sir."]))
    rt = SimpleNamespace(config=load_config(), paths=SimpleNamespace(data=tmp_path / "data"))
    results, path = me.run_live(rt, "fake", category="knowledge-update")
    assert len(results) == 4 and path.exists()
    assert {r.id for r in results if r.passed} == {"ku-1", "ku-2"}
    assert "Stale-answer rate (knowledge-update): 0/4" in me.format_live(results)
