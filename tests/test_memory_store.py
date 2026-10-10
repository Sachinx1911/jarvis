from datetime import date

import pytest

from jarvis.db import Store
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryRejected, MemoryStore


@pytest.fixture
def mem(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    yield MemoryStore(tmp_path, store)
    store.close()


def _m(name, **kw):
    kw.setdefault("evidence", name)
    return Memory(name=name, **kw)


def test_save_writes_markdown_and_index(mem, tmp_path):
    m = mem.save(_m("demo project run", type="procedure", body="make run", keywords="demo project chalav"))
    assert m.id == "m-0001"
    files = list((tmp_path / "memory" / "procedures").glob("m-0001-*.md"))
    assert len(files) == 1
    again = Memory.from_markdown(files[0].read_text(encoding="utf-8"))
    assert again.body == "make run" and again.type == "procedure"
    assert "m-0001" in (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_evidence_required(mem):
    with pytest.raises(ValueError):
        mem.save(Memory(name="x", evidence=""))


def test_secrets_never_stored(mem, tmp_path):
    with pytest.raises(MemoryRejected):
        mem.save(_m("wifi", body="password: hunter22"))
    assert not list((tmp_path / "memory").rglob("m-*.md"))


def test_search_words_devanagari_and_typos(mem):
    a = mem.save(_m("college project", body="माझा कॉलेज प्रोजेक्ट make run ने चालतो", keywords="college project karaycha"))
    mem.save(_m("tea preference", type="preference", body="drinks tea, not coffee", keywords="tea chai"))
    assert [h.memory.id for h in mem.search("प्रोजेक्ट")] == [a.id]
    assert [h.memory.id for h in mem.search("karaicha")] == [a.id]  # typo, via trigrams
    assert [h.memory.id for h in mem.search("college")][0] == a.id
    assert mem.search("bicycle") == []  # gate: no match, no results


def test_stopwords_only_query_returns_nothing(mem):
    mem.save(_m("anything", body="something"))
    assert mem.search("kay ahe") == []


def test_supersede_keeps_old(mem):
    old = mem.save(_m("office city", body="office is in Pune", subject="office"))
    new = mem.supersede(old.id, _m("office city new", body="office moved to Mumbai"))
    old_again = mem.get(old.id)
    assert old_again.status == "superseded" and old_again.superseded_by == new.id
    assert old_again.valid_until == date.today().isoformat()
    assert new.subject == "office"
    assert [h.memory.id for h in mem.search("office")] == [new.id]  # only active


def test_archive_and_list(mem):
    a = mem.save(_m("one"))
    mem.save(_m("two"))
    mem.archive(a.id)
    assert [m.name for m in mem.list()] == ["two"]
    assert len(mem.list(status=None)) == 2


def test_inferred_capped(mem):
    m = mem.save(_m("guess", source="inferred", confidence="high"))
    assert m.confidence == "medium"


def test_reindex_after_manual_edit(mem, tmp_path):
    m = mem.save(_m("bike service", body="every 3000 km"))
    path = next((tmp_path / "memory").rglob("m-0001-*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("every 3000 km", "every 5000 km"), encoding="utf-8")
    assert mem.reindex() == 1
    assert mem.get(m.id).body == "every 5000 km"
    assert mem.search("5000")


def test_sensitive_hidden_in_memory_md(mem, tmp_path):
    mem.save(_m("health note", body="takes medicine daily", sensitivity="sensitive"))
    assert "(sensitive)" in (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "medicine" not in (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_export(mem, tmp_path):
    mem.save(_m("one"))
    assert mem.export(tmp_path / "out.json") == 1
