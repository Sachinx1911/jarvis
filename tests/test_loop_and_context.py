from datetime import datetime

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop
from jarvis.core.chat import ChatSession
from jarvis.db import Store
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryStore
from jarvis.providers.base import ToolResult
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.skills.loader import SkillLibrary

DECISION = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store)
    yield tmp_path, store, mem
    store.close()


def _session(env, script=None):
    home, store, mem = env
    provider = FakeProvider(script=script)
    s = ChatSession(load_config(), provider, DECISION, store, AuditLog(home / "data" / "audit.jsonl"),
                    now=lambda: datetime(2026, 10, 10, 19, 30), home=home, memory=mem,
                    skills=SkillLibrary(home / "skills"))
    return s, provider


def test_relevant_memory_and_constraints_in_prompt(env):
    _, _, mem = env
    mem.save(Memory(name="demo run", type="procedure", summary_en="Demo project runs with make run.",
                    keywords="demo project run chalav", body="make run", evidence="make run ne chalto"))
    mem.save(Memory(name="no early meetings", type="constraint", summary_en="No meetings before 10 am.",
                    body="never before 10", evidence="never put meetings before 10 am"))
    s, provider = _session(env)
    s.send("demo project kasa chalvaycha?")
    system = provider.requests[0].system
    assert "Demo project runs with make run." in system
    assert "## Hard rules" in system and "No meetings before 10 am." in system
    assert system.rstrip().endswith("Local time: 2026-10-10 19:30")


def test_sensitive_memory_withheld_from_cloud_route(env):
    _, _, mem = env
    mem.save(Memory(name="medicine", summary_en="Takes bp tablet every morning.", keywords="medicine tablet",
                    body="bp tablet", evidence="bp tablet", sensitivity="sensitive"))
    s, provider = _session(env)
    s.send("which tablet do I take?")
    system = provider.requests[0].system
    assert "bp tablet" not in system and "1 sensitive memories or private document parts were withheld" in system


def test_tool_loop_memory_search(env):
    _, _, mem = env
    mem.save(Memory(name="tea", type="preference", summary_en="Prefers tea.", keywords="tea chai",
                    body="tea, no coffee", evidence="only tea"))
    s, provider = _session(env, [{"tool": "memory_search", "arguments": {"query": "chai"}}, "You prefer tea, sir."])
    assert s.send("what do I drink?") == "You prefer tea, sir."
    tool_msg = provider.requests[1].messages[-1]
    assert tool_msg.role == "tool" and "Prefers tea." in tool_msg.parts[0].content
    assert {"memory_search", "session_search", "load_skill"} <= {t.name for t in provider.requests[0].tools}


def test_bad_tool_args_return_error_not_crash(env):
    s, provider = _session(env, [{"tool": "memory_search", "arguments": {"q": 1}}, "ok"])
    assert s.send("x") == "ok"
    result = provider.requests[1].messages[-1].parts[0]
    assert isinstance(result, ToolResult) and result.is_error


def test_step_limit(env):
    s, _ = _session(env, [{"tool": "session_search", "arguments": {"query": "abc"}}] * 10)
    assert "too many steps" in s.send("loop forever")


def test_p3_redacted_before_provider(env):
    s, provider = _session(env)
    s.send("my password: hunter22 please keep it")
    assert "hunter22" not in provider.requests[0].messages[-1].text_content()


def test_emergency_stop_blocks_calls(env):
    s, provider = _session(env)
    s.stop.engage("test")
    with pytest.raises(EmergencyStop):
        s.send("hello")
    assert provider.requests == []
    s.stop.release()
    assert s.send("hello") == "Good evening, sir."


def test_skill_index_and_load(env):
    home, _, _ = env
    (home / "skills" / "make-tea").mkdir(parents=True)
    (home / "skills" / "make-tea" / "SKILL.md").write_text(
        "---\nname: make-tea\ndescription: How the user likes tea made\n---\nBoil water. Add milk.\n", encoding="utf-8")
    s, provider = _session(env, [{"tool": "load_skill", "arguments": {"name": "make-tea"}}, "done"])
    s.send("make tea")
    assert "- make-tea: How the user likes tea made" in provider.requests[0].system
    assert "Boil water" in provider.requests[1].messages[-1].parts[0].content


def test_skill_load_refuses_unknown_paths(tmp_path):
    assert SkillLibrary(tmp_path).load("../../etc/passwd") is None


def test_session_search_finds_past_conversation(env):
    s1, _ = _session(env)
    s1.send("the demo bike is red")
    s2, provider = _session(env, [{"tool": "session_search", "arguments": {"query": "bike"}}, "ok"])
    s2.send("what colour?")
    assert "the demo bike is red" in provider.requests[1].messages[-1].parts[0].content


# ---- past-chat excerpts and notes-before-answer (research 2026-10-10, topic 4) ----

def test_past_chat_excerpts_next_to_memories(env):
    s1, _ = _session(env)
    s1.send("mazi gaadi pandhri Swift ahe")
    s2, provider = _session(env)
    s2.send("माझी गाडी कोणती आहे?")
    system = provider.requests[0].system
    assert "## Past chat excerpts (raw words from earlier chats; may be outdated)" in system
    assert "mazi gaadi pandhri Swift ahe" in system
    assert "माझी गाडी कोणती आहे?" not in system.split("## Past chat excerpts")[1]  # never the message being answered
    assert s2.context.build("x", datetime(2026, 10, 10, 19, 30)).excerpt_ids == []


def test_excerpts_respect_budget_privacy_and_switch(env):
    _, _, mem = env
    mem.save(Memory(name="medicine", summary_en="Takes a bp tablet.", keywords="tablet",
                    body="bp tablet roj", evidence="mi roj bp tablet ghetla", sensitivity="sensitive"))
    s1, _ = _session(env)
    s1.send("mi roj bp tablet ghetla")
    for i in range(6):
        s1.send(f"tablet note {i} " + "x" * 400)
    s2, provider = _session(env)
    s2.send("tablet")
    system = provider.requests[0].system
    block = system.split("## Past chat excerpts")[1] if "## Past chat excerpts" in system else ""
    assert "bp tablet" not in system                      # quotes a memory this route may not see
    assert len(block) < 1200 and block.count("\n- [") <= 3  # 1-3 excerpts within the size budget
    s2.context.options.excerpts = False
    assert "## Past chat excerpts" not in s2.context.build("tablet", datetime(2026, 10, 10, 19, 30)).system


def test_memory_lines_carry_their_date(env):
    _, _, mem = env
    mem.save(Memory(name="office", summary_en="The office moved to Baner.", keywords="office baner",
                    body="Baner", evidence="office Baner la", valid_from="2026-09-20"))
    s, provider = _session(env)
    s.send("office kuthe ahe?")
    assert "saved 2026-09-20" in provider.requests[0].system


def test_system_prompt_asks_for_silent_notes_and_abstention(env):
    s, provider = _session(env)
    s.send("hello")
    system = provider.requests[0].system
    assert "first work out silently which memories and past-chat excerpts" in system
    assert "Do not show these notes to the user." in system
    assert "say plainly that you don't know" in system