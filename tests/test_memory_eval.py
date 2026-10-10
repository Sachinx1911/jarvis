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
    # the old value as history is fine; as the current value it is stale
    assert me.check_answer(q, "It moved from Hinjewadi to Baner.") == (True, False, "ok")
    assert me.check_answer(q, "- Tumcha office ata Baner la ahe. - Adhi Hinjewadi la hota.")[0]
    for wrong in ("Your office is in Hinjewadi, sir.", "Baner, or maybe Hinjewadi.", "ऑफिस Hinjewadi ला आहे."):
        ok, stale, _ = me.check_answer(q, wrong)
        assert not ok and stale
    plan = {"category": "knowledge-update", "answer": {"contains_any": ["399"], "not_contains": ["299"]},
            "stale_values": ["299"]}
    assert me.check_answer(plan, "You're on the ₹399 plan (before that it was the ₹299 plan).")[0]
    assert not me.check_answer(plan, "You're on the ₹299 plan, sir.")[0]
    assert not me.check_answer(plan, "Your plan was changed to ₹299; the ₹399 offer ended.")[0]
    un = {"category": "unanswerable"}
    assert me.check_answer(un, "I don't know, sir.")[0]
    assert me.check_answer(un, "मला माहित नाही, sir.")[0]
    assert not me.check_answer(un, "It is 42.")[0]
    for declined in ("I'm afraid I don't have it, sir.", "tumchya aai chya vayachi mahiti mazya memory madhe nahi.",
                     "मागच्या वर्षीच्या सहलीची माझ्याकडे नोंद नाही."):
        assert me.check_answer(un, declined)[0]
    assert not me.check_answer(un, "Your mother is 58, sir.")[0]


def _question(qid: str) -> dict:
    return next(q for q in me.load_cases()["questions"] if q["id"] == qid)


def test_baner_accepts_both_devanagari_spellings():
    for qid in ("ku-1", "ku-2", "ms-3"):          # every question whose answer is Baner
        q = _question(qid)
        assert {"Baner", "बाणेर", "बानेर"} <= set(q["answer"]["contains_any"]), qid
    ku2 = _question("ku-2")
    for right in ("तुमचं ऑफिस आता बानेरला आहे, सर.", "ऑफिस आता बाणेरमध्ये आहे.", "Office ata Banerla ahe."):
        assert me.check_answer(ku2, right) == (True, False, "ok"), right


def test_baner_spellings_do_not_accept_a_wrong_place():
    ku2 = _question("ku-2")
    for wrong in ("तुमचं ऑफिस हिंजवडीला आहे.", "ऑफिस आता बालेवाडीत आहे.", "बानेर नाही, ऑफिस Hinjewadi ला आहे."):
        assert not me.check_answer(ku2, wrong)[0], wrong


def test_tm1_accepts_the_old_lift_named_as_history():
    tm1 = _question("tm-1")
    for right in ("Last week you deadlifted 100 kilo (1 October). The previous best was 80 kilo in September.",
                  "Gelya athavdyat 100 kilo deadlift kela. Tyaadhi 80 kilo hota.",
                  "1 October: 100 kilo, sir."):
        assert me.check_answer(tm1, right)[0], right


def test_tm1_rejects_the_old_lift_as_last_weeks_answer():
    tm1 = _question("tm-1")
    for wrong in ("Last week you deadlifted 80 kilo, sir.",
                  "You did 100 kilo on 1 October and 80 kilo last week.",
                  "Gelya athavdyat 80 kilo kela. Pudhcha target 100 kilo."):
        assert not me.check_answer(tm1, wrong)[0], wrong


def test_live_run_uses_the_chat_route_with_a_fake_provider(tmp_path, monkeypatch):
    from jarvis.config import load_config
    from jarvis.providers.fake import FakeProvider

    monkeypatch.setattr("jarvis.providers.make_provider", lambda name, config: FakeProvider(script=["Baner, sir."]))
    rt = SimpleNamespace(config=load_config(), paths=SimpleNamespace(data=tmp_path / "data"))
    results, path = me.run_live(rt, "fake", category="knowledge-update")
    assert len(results) == 4 and path.exists()
    assert {r.id for r in results if r.passed} == {"ku-1", "ku-2"}
    assert "Stale-answer rate (knowledge-update): 0/4" in me.format_live(results)
