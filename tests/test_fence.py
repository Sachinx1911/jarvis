"""Workspace tool fences (jarvis/control/fence.py, PLAN.md 27.3): narrow, never widen; always_ask."""

import json

import pytest

from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.control.fence import Fence, fence_from_workspace
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolSpec
from jarvis.tools.registry import Tool, ToolRegistry
from jarvis.workspaces.model import Workspace

OBJ = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


class Approver:
    def __init__(self, answer=True):
        self.answer = answer
        self.asked = []

    def __call__(self, req):
        self.asked.append(req)
        return self.answer


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "jarvis.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    yield store, audit, tmp_path
    store.close()


def _audit(tmp):
    p = tmp / "audit.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _reg(env, approver=None, fence=None):
    store, audit, _ = env
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit, approver))
    reg.register(Tool(ToolSpec("read_thing", "x", OBJ), "T0", lambda a: "read", taints=False))
    reg.register(Tool(ToolSpec("write_thing", "x", OBJ), "T1", lambda a: "written", taints=False))
    reg.register(Tool(ToolSpec("send_thing", "x", OBJ), "T3", lambda a: "sent"))
    if fence is not None:
        reg.set_fence(fence, fence.workspace)
    return reg


# ---- the fence itself ----

def test_fence_from_workspace():
    w = Workspace("acme", "Acme", tools_allow=("read_thing", "write_thing"), tools_deny=("write_thing",),
                  always_ask=("read_thing",))
    f = fence_from_workspace(w)
    assert f.workspace == "acme"
    assert f.refusal("read_thing") is None
    assert "denied" in f.refusal("write_thing")            # deny wins over allow
    assert "not in the allowed" in f.refusal("send_thing")  # not listed
    assert "always asks" in f.ask_reason("read_thing")
    assert f.ask_reason("write_thing") is None


def test_empty_allow_means_every_registered_tool():
    f = Fence(deny=frozenset({"send_thing"}))
    assert f.refusal("anything") is None and f.refusal("send_thing")


def test_two_fences_only_narrow():
    a = Fence(allow=frozenset({"x", "y"}), deny=frozenset({"z"}), always_ask=frozenset({"x"}), workspace="acme")
    b = Fence(allow=frozenset({"y", "w"}), deny=frozenset({"q"}), always_ask=frozenset({"y"}))
    c = a.narrowed_by(b)
    assert c.allow == {"y"} and c.deny == {"z", "q"} and c.always_ask == {"x", "y"} and c.workspace == "acme"
    assert Fence().narrowed_by(b).allow == {"y", "w"}  # an open fence takes the other's allow list


# ---- in the registry ----

def test_denied_and_unlisted_tools_are_refused_and_audited(env):
    reg = _reg(env, Approver(), Fence(allow=frozenset({"read_thing", "send_thing"}), deny=frozenset({"send_thing"}),
                                      workspace="acme"))
    denied = reg.execute(ToolCall("1", "send_thing", {"q": "a"}))
    assert denied.is_error and "denied in workspace acme" in denied.content
    unlisted = reg.execute(ToolCall("2", "write_thing", {"q": "a"}))
    assert unlisted.is_error and "not in the allowed tools" in unlisted.content
    assert not reg.execute(ToolCall("3", "read_thing", {"q": "a"})).is_error
    events = _audit(env[2])
    fenced = [e for e in events if e["event"] == "tool_fenced"]
    assert [e["tool"] for e in fenced] == ["send_thing", "write_thing"] and fenced[0]["workspace"] == "acme"
    assert [e["decision"] for e in events if e["event"] == "tool_run"][:2] == ["refused_fence", "refused_fence"]
    assert [s.name for s in reg.specs()] == ["read_thing"]  # the model never sees fenced-out tools


def test_fence_never_widens(env):
    """A tool in the allow list that the registry does not hold stays absent; a role restriction
    on top of the fence still holds."""
    reg = _reg(env, Approver(), Fence(allow=frozenset({"read_thing", "delete_everything"}), workspace="acme"))
    gone = reg.execute(ToolCall("1", "delete_everything", {"q": "a"}))
    assert gone.is_error and "unknown or disabled" in gone.content
    reg.restrict({"write_thing"})  # the role allows only write_thing, the fence only read_thing
    assert reg.specs() == []
    assert reg.execute(ToolCall("2", "read_thing", {"q": "a"})).is_error


def test_always_ask_forces_approval_on_t0(env):
    ap = Approver(answer=True)
    reg = _reg(env, ap, Fence(always_ask=frozenset({"read_thing"}), workspace="acme"))
    out = reg.execute(ToolCall("1", "read_thing", {"q": "a"}))
    assert not out.is_error and out.content == "read"
    assert len(ap.asked) == 1 and ap.asked[0].tier == "T0" and "always asks before read_thing" in ap.asked[0].reason
    assert not reg.execute(ToolCall("2", "write_thing", {"q": "a"})).is_error and len(ap.asked) == 1  # not listed


def test_always_ask_denied_without_approver(env):
    reg = _reg(env, None, Fence(always_ask=frozenset({"read_thing"})))
    out = reg.execute(ToolCall("1", "read_thing", {"q": "a"}))
    assert out.is_error and "nobody can approve" in out.content


def test_always_ask_beats_standing_grant(env, tmp_path):
    """always_ask means always: a standing grant may not answer for Sachin."""
    store, audit, _ = env
    ap = Approver(answer=True)
    reg = _reg(env, ap, Fence(always_ask=frozenset({"write_thing"})))
    reg.gate.grants.create("write_thing", "T1", {"q": {"max_chars": 10}}, 7, 5)
    reg.tainted = True  # T1 would otherwise be answered by the grant
    assert not reg.execute(ToolCall("1", "write_thing", {"q": "a"})).is_error
    assert len(ap.asked) == 1


def test_no_fence_changes_nothing(env):
    ap = Approver()
    reg = _reg(env, ap)
    assert not reg.execute(ToolCall("1", "read_thing", {"q": "a"})).is_error
    assert ap.asked == [] and len(reg.specs()) == 3
