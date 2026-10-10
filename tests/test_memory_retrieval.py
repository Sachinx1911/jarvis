"""Cross-script, time-aware and fact-augmented retrieval (research 2026-10-10, topic 4)."""

import json
from datetime import date

import pytest

from jarvis.db import Store
from jarvis.memory import session_facts
from jarvis.memory.model import Memory
from jarvis.memory.quiet import extraction_record, mark_extracted
from jarvis.memory.store import MemoryStore
from jarvis.memory.timefilter import DateRange

TODAY = date(2026, 10, 10)


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    yield tmp_path, store, MemoryStore(tmp_path, store)
    store.close()


def _m(name, **kw):
    kw.setdefault("evidence", kw.get("body") or name)
    return Memory(name=name, **kw)


def _chat(store, session_id, ts, *lines):
    """Store past messages with a fixed UTC time (as db.add_message would, minus the clock)."""
    ids = []
    for role, text in lines:
        parts = json.dumps([{"type": "TextPart", "text": text}], ensure_ascii=False)
        cur = store.conn.execute("INSERT INTO messages (session_id, ts, role, parts) VALUES (?, ?, ?, ?)",
                                 (session_id, ts, role, parts))
        store.conn.execute("INSERT INTO session_text (message_id, session_id, role, ts, text) VALUES (?, ?, ?, ?, ?)",
                           (cur.lastrowid, session_id, role, ts, text))
        ids.append(cur.lastrowid)
    store.conn.commit()
    return ids


# ---- 1. both scripts ----

def test_romanized_query_finds_devanagari_memory_and_back(env):
    _, _, mem = env
    sister = mem.save(_m("sister city", body="माझी बहीण मीरा पुण्यात राहते", keywords="sister बहीण"))
    car = mem.save(_m("car", body="mazi gaadi pandhri Swift ahe", keywords="car gaadi"))
    assert [h.memory.id for h in mem.search("bahin kuthe rahate")][0] == sister.id
    assert [h.memory.id for h in mem.search("माझी गाडी कोणती")][0] == car.id


def test_script_forms_switch_off_restores_plain_search(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store, script_forms=False)
    mem.save(_m("sister city", body="माझी बहीण पुण्यात राहते", keywords="sister"))
    assert mem.search("bahin") == []
    store.close()


def test_devanagari_stopwords_do_not_match_everything(env):
    _, _, mem = env
    mem.save(_m("anything", body="काहीतरी वेगळं"))
    assert mem.search("माझा काय आहे") == []


# ---- 2. time-aware ----

def test_time_range_ranks_memories_saved_then_first(env):
    _, _, mem = env
    old = mem.save(_m("gym trainer", body="gym cha trainer badalla", valid_from="2026-07-20"))
    new = mem.save(_m("gym deadlift", body="gym madhe deadlift kela", valid_from="2026-10-01"))
    hits = mem.search("gelya athavdyat gym", today=TODAY)
    assert hits[0].memory.id == new.id and {h.memory.id for h in hits} == {old.id, new.id}  # a boost, not a filter


def test_time_only_question_lists_memories_from_then(env):
    _, _, mem = env
    mem.save(_m("old note", body="juni goshta", valid_from="2026-07-01"))
    recent = mem.save(_m("bag place", body="laptop bag kapatat", valid_from="2026-10-02"))
    hits = mem.search("last week", today=TODAY)
    assert [h.memory.id for h in hits] == [recent.id]


def test_time_aware_switch_and_explicit_range(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store, time_aware=False)
    mem.save(_m("bag place", body="laptop bag kapatat", valid_from="2026-10-02"))
    assert mem.search("last week", today=TODAY) == []      # no range: "last week" is just words
    assert mem.resolve_range("x", DateRange(TODAY, TODAY)) is None
    store.close()


# ---- 3. fact-augmented session search ----

def test_extracted_facts_make_a_session_findable(env):
    _, store, mem = env
    wedding = mem.save(_m("brother's wedding", summary_en="The user's brother's wedding is in December.",
                          keywords="brother wedding december", body="bhavacha lagna December madhe",
                          evidence="mazya bhavacha lagna December madhe ahe"))
    mid = _chat(store, "a1b2c3d4e5f6", "2026-08-05 14:00:00",
                ("user", "mazya bhavacha lagna December madhe ahe"), ("assistant", "Congratulations, sir."))[0]
    conn = store.conn
    assert session_facts.search(conn, "brother wedding", use_facts=True) == []   # not indexed yet
    mark_extracted(conn, "a1b2c3d4e5f6", [("ADD", wedding.id), ("NOOP", "-")])
    assert extraction_record(conn, "a1b2c3d4e5f6")["extracted_at"]
    hits = session_facts.search(conn, "brother wedding")
    assert hits[0].message_id == mid and "fact" in hits[0].via and hits[0].memory_ids == [wedding.id]
    assert session_facts.search(conn, "brother wedding", use_facts=False) == []


def test_sensitive_facts_are_not_indexed(env):
    _, store, mem = env
    med = mem.save(_m("medicine", summary_en="Takes a bp tablet.", keywords="medicine tablet",
                      body="roj bp chi goli", sensitivity="sensitive"))
    _chat(store, "a1b2c3d4e5f7", "2026-08-05 14:00:00", ("user", "roj bp chi goli"))
    assert session_facts.index_session(store.conn, "a1b2c3d4e5f7", [("ADD", med.id)]) == 0


def test_reindex_all_rebuilds_from_extraction_records(env):
    _, store, mem = env
    m = mem.save(_m("car", summary_en="The user's car is a white Swift.", body="gaadi pandhri swift",
                    evidence="gaadi pandhri swift ahe"))
    _chat(store, "a1b2c3d4e5f8", "2026-04-10 12:00:00", ("user", "gaadi pandhri swift ahe"))
    mark_extracted(store.conn, "a1b2c3d4e5f8", [("ADD", m.id)])
    store.conn.execute("DELETE FROM session_facts")
    assert session_facts.reindex_all(store.conn) == 1


def test_cross_script_session_search_and_lazy_keys(env):
    _, store, _ = env
    a = _chat(store, "a1b2c3d4e5f9", "2026-09-12 10:00:00", ("user", "aaj 3 pustaka ghetli"))[0]
    b = _chat(store, "a1b2c3d4e5fa", "2026-09-27 10:00:00", ("user", "आज २ पुस्तकं घेतली"))[0]
    ids = {h.message_id for h in session_facts.search(store.conn, "kiti pustaka ghetli")}
    assert {a, b} <= ids
    assert session_facts.sync_keys(store.conn) == 0          # already caught up
    c = _chat(store, "a1b2c3d4e5fb", "2026-10-01 10:00:00", ("user", "navin pustak vachla"))[0]
    assert c in {h.message_id for h in session_facts.search(store.conn, "पुस्तक")}
    assert {h.message_id for h in session_facts.search(store.conn, "pustaka", script_forms=False)} == {a}


def test_session_time_boost_and_narrow_range(env):
    _, store, _ = env
    old = _chat(store, "a1b2c3d4e600", "2026-09-08 02:00:00", ("user", "gym madhe deadlift 80 kilo kela"))[0]
    new = _chat(store, "a1b2c3d4e601", "2026-10-01 02:00:00", ("user", "gym madhe 100 kilo deadlift kela"))[0]
    hits = session_facts.search(store.conn, "gelya athavdyat gym deadlift", today=TODAY)
    assert hits[0].message_id == new and "time" in hits[0].via
    assert {h.message_id for h in hits} == {old, new}
    # yesterday's chat in another script and language ("gym" vs "जिम") is still a candidate
    y = _chat(store, "a1b2c3d4e602", "2026-10-09 06:00:00", ("user", "आज जिमला गेलो नाही"))[0]
    assert y in {h.message_id for h in session_facts.search(store.conn, "kal gym baddal", today=TODAY)}


def test_superseded_lines_rank_lower_and_are_flagged(env):
    _, store, mem = env
    old = mem.save(_m("office old", summary_en="The office is in Hinjewadi.", keywords="office",
                      body="maza office Hinjewadi la ahe", valid_from="2026-03-01"))
    old_mid = _chat(store, "a1b2c3d4e603", "2026-03-01 05:00:00", ("user", "maza office Hinjewadi la ahe"))[0]
    mark_extracted(store.conn, "a1b2c3d4e603", [("ADD", old.id)])
    new = mem.supersede(old.id, _m("office new", summary_en="The office moved to Baner.", keywords="office",
                                   body="office ata Baner la shift zala"))
    new_mid = _chat(store, "a1b2c3d4e604", "2026-09-20 05:00:00", ("user", "office ata Baner la shift zala"))[0]
    mark_extracted(store.conn, "a1b2c3d4e604", [("SUPERSEDE", new.id)])
    hits = session_facts.search(store.conn, "majha office")
    assert [h.message_id for h in hits] == [new_mid, old_mid]
    assert hits[1].superseded == [old.id] and hits[0].superseded == []


def test_exclude_session_and_latest_session(env):
    _, store, _ = env
    _chat(store, "a1b2c3d4e605", "2026-09-01 05:00:00", ("user", "garden madhe tomato lavle"))
    _chat(store, "a1b2c3d4e606", "2026-10-10 05:00:00", ("user", "garden kasa ahe?"))
    assert session_facts.latest_session(store.conn, "garden  kasa ahe?") == "a1b2c3d4e606"
    assert session_facts.latest_session(store.conn, "something else") is None
    hits = session_facts.search(store.conn, "garden", exclude_session="a1b2c3d4e606")
    assert [h.session_id for h in hits] == ["a1b2c3d4e605"]


def test_index_failure_never_breaks_mark_extracted(env, monkeypatch):
    _, store, _ = env
    import sqlite3

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk")

    monkeypatch.setattr(session_facts, "index_session", boom)
    mark_extracted(store.conn, "a1b2c3d4e607", [("ADD", "m-9999")])
    assert extraction_record(store.conn, "a1b2c3d4e607")["extracted_at"]
