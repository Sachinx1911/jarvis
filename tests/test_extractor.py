import pytest

from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.memory.extract import Extractor
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryRejected, MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision

DECISION = RouteDecision("memory_extractor", "fake", "fake-1", "low", "test")


def _cand(**kw):
    base = {"name": "bike service", "type": "fact", "subject": "bike", "summary_en": "The bike needs service every 3000 km.",
            "keywords": "bike service km", "when_to_use": "bike maintenance", "sensitivity": "normal",
            "evidence": "my bike needs servicing every 3000 km", "source": "user-said", "body": "every 3000 km"}
    return {**base, **kw}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store)
    yield mem, AuditLog(tmp_path / "data" / "audit.jsonl")
    store.close()


def _ex(env, script):
    mem, audit = env
    return Extractor(mem, FakeProvider(script=script), DECISION, audit), mem


def test_remember_enriches(env):
    ex, mem = _ex(env, [{"json": {"name": "Tea preference", "type": "preference", "subject": "user",
                                   "summary_en": "The user prefers tea.", "keywords": "tea chai",
                                   "when_to_use": "drinks", "sensitivity": "normal"}}])
    m = ex.remember("mala chai avadte")
    assert (m.type, m.summary_en, m.evidence) == ("preference", "The user prefers tea.", "mala chai avadte")


def test_remember_falls_back_without_valid_json(env):
    ex, mem = _ex(env, ["not json"])
    m = ex.remember("demo project runs with make run")
    assert m.body == "demo project runs with make run" and m.summary_en == ""


def test_remember_private_sends_nothing(env):
    provider = FakeProvider()
    mem, audit = env
    m = Extractor(mem, provider, DECISION, audit).remember("bp tablet every morning", private=True)
    assert m.sensitivity == "sensitive" and provider.requests == []


def test_remember_rejects_secret_before_sending(env):
    provider = FakeProvider()
    mem, audit = env
    with pytest.raises(MemoryRejected):
        Extractor(mem, provider, DECISION, audit).remember("bank password: abc123")
    assert provider.requests == []


def test_extract_adds_quoted_candidate_only(env):
    ex, mem = _ex(env, [{"json": {"candidates": [
        _cand(),
        _cand(name="made up", evidence="I love opera"),  # not a quote: rejected
    ]}}])
    results = ex.extract_session(["My bike needs servicing every 3000 km", "what is 2+2"])
    assert results[0][0] == "ADD" and results[1][0] == "REJECT"
    assert len(mem.list()) == 1


def test_extract_sees_only_user_messages_and_skips_commands(env):
    provider = FakeProvider(script=[{"json": {"candidates": []}}])
    mem, audit = env
    Extractor(mem, provider, DECISION, audit).extract_session(["hello", "/memory tea"])
    sent = provider.requests[0].messages[0].text_content()
    assert "hello" in sent and "/memory" not in sent


def test_extract_supersedes_similar(env):
    mem, audit = env
    old = mem.save(Memory(name="bike service", subject="bike", summary_en="Bike service every 2000 km.",
                          keywords="bike service km", evidence="bike service every 2000 km"))
    ex = Extractor(mem, FakeProvider(script=[
        {"json": {"candidates": [_cand()]}},
        {"json": {"action": "SUPERSEDE", "target_id": old.id}},
    ]), DECISION, audit)
    results = ex.extract_session(["my bike needs servicing every 3000 km"])
    assert results[0][0] == "SUPERSEDE"
    assert mem.get(old.id).status == "superseded"


def test_extract_unknown_target_rejected(env):
    mem, audit = env
    mem.save(Memory(name="bike service", summary_en="Bike service.", keywords="bike service", evidence="bike"))
    ex = Extractor(mem, FakeProvider(script=[
        {"json": {"candidates": [_cand()]}},
        {"json": {"action": "UPDATE", "target_id": "m-9999"}},
    ]), DECISION, audit)
    assert ex.extract_session(["my bike needs servicing every 3000 km"])[0][0] == "REJECT"


def test_extract_invalid_schema_saves_nothing(env):
    ex, mem = _ex(env, [{"json": {"candidates": [{"name": "x"}]}}])
    assert ex.extract_session(["my bike needs servicing every 3000 km"]) == []
    assert mem.list() == []


def test_keywords_get_both_scripts(env):
    ex, mem = _ex(env, [{"json": {"name": "Sister city", "type": "fact", "subject": "sister",
                                   "summary_en": "The user's sister lives in Pune.", "keywords": "sister pune bahin",
                                   "when_to_use": "family", "sensitivity": "normal"}}])
    m = ex.remember("माझी बहीण पुण्यात राहते")
    words = m.keywords.split()
    assert {"sister", "bahin", "बहिन"} <= set(words)          # romanized keyword -> Devanagari guess
    assert {"बहीण", "punyat"} <= set(words)                   # the note's own Devanagari words + their romanized keys
    assert not any(w.startswith("सिस") for w in words)        # English words stay English
    # no model at all: the note's Devanagari words still get romanized keys
    plain = Extractor(mem, None, None, AuditLog(mem.root.parent / "data" / "audit2.jsonl")).remember("माझा भाऊ नाशिकला")
    assert {"bhau", "nashikla"} <= set(plain.keywords.split())


def test_extracted_candidates_get_both_scripts(env):
    ex, mem = _ex(env, [{"json": {"candidates": [_cand(keywords="bike service gaadi")]}}])
    assert ex.extract_session(["my bike needs servicing every 3000 km"])[0][0] == "ADD"
    saved = mem.list()[0]
    assert "गादि" in saved.keywords.split() and "bike" in saved.keywords.split()

def test_sensitive_neighbours_never_reach_the_model(env):
    mem, audit = env
    private = mem.save(Memory(name="bike loan", subject="bike", sensitivity="sensitive",
                              summary_en="Bike loan EMI of 4000 rupees on the 5th.", body="bike loan EMI 4000 on the 5th",
                              keywords="bike loan emi", evidence="bike loan emi 4000"))
    normal = mem.save(Memory(name="bike service", subject="bike", summary_en="Bike service every 2000 km.",
                             keywords="bike service km", evidence="bike service every 2000 km"))
    provider = FakeProvider(script=[{"json": {"candidates": [_cand()]}},
                                    {"json": {"action": "SUPERSEDE", "target_id": normal.id}}])
    results = Extractor(mem, provider, DECISION, audit).extract_session(["my bike needs servicing every 3000 km"])
    decide_prompt = provider.requests[1].messages[0].text_content()
    assert normal.id in decide_prompt
    assert private.id not in decide_prompt and "EMI" not in decide_prompt and "4000" not in decide_prompt
    assert results[0] == ("SUPERSEDE", results[0][1])


def test_duplicate_of_a_private_memory_is_caught_locally(env):
    mem, audit = env
    private = mem.save(Memory(name="bp tablet", subject="health", sensitivity="sensitive", body="every 3000 km",
                              summary_en="private", keywords="bike service km", evidence="x"))
    provider = FakeProvider(script=[{"json": {"candidates": [_cand()]}}])
    results = Extractor(mem, provider, DECISION, audit).extract_session(["my bike needs servicing every 3000 km"])
    assert results[0] == ("NOOP", private.id) and len(provider.requests) == 1   # no decide call at all


def test_private_memory_with_a_different_name_is_not_superseded_blindly(env):
    mem, audit = env
    old = mem.save(Memory(name="mom morning tablet", subject="mom", sensitivity="sensitive", body="8 am",
                          summary_en="Mom's morning tablet at 8.", keywords="mom tablet", evidence="x"))
    provider = FakeProvider(script=[{"json": {"candidates": [
        _cand(name="mom evening walk", subject="mom", keywords="mom tablet walk", summary_en="Mom walks at 6 pm.",
              evidence="aai sandhyakali 6 la firayla jate", body="6 pm walk")]}}])
    results = Extractor(mem, provider, DECISION, audit).extract_session(["aai sandhyakali 6 la firayla jate"])
    assert results[0][0] == "ADD" and mem.get(old.id).status == "active" and len(provider.requests) == 1
