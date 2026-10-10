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