"""The laws test (PLAN.md 27.7): every declared kind has its three powers, says who owns it and
where its truth lives; the rule of sight exists in one place only; nothing deletes silently.

A kind may declare a gap (with the step that closes it). An undeclared gap fails the test.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

from jarvis.core.kinds import KINDS, MARKS, by_name

PACKAGE = Path(__file__).resolve().parent.parent / "jarvis"


def _store_class(kind):
    module, _, cls = kind.store.partition(":")
    return getattr(importlib.import_module(module), cls)


@pytest.mark.parametrize("kind", KINDS, ids=[k.name for k in KINDS])
def test_every_kind_has_its_three_powers(kind):
    """Law 2: create, preserve, end. A missing power must be a declared gap, never silent."""
    store = _store_class(kind)
    if kind.create != "-":
        assert callable(getattr(store, kind.create, None)), f"{kind.name}: no create method {kind.create}"
    else:
        assert any("create" in g for g in kind.gaps), f"{kind.name}: create is '-' but no gap declares it"
    for name in kind.preserve:
        assert callable(getattr(store, name, None)), f"{kind.name}: no preserve method {name}"
    if kind.end not in (None, "-"):
        assert callable(getattr(store, kind.end, None)), f"{kind.name}: no end method {kind.end}"
    elif kind.end is None:
        assert any(("end" in g) or ("archive" in g) for g in kind.gaps), \
            f"{kind.name}: end is missing but no gap declares it"
    else:  # "-": only the audit log may be endless, by law 3
        assert kind.name == "audit"


@pytest.mark.parametrize("kind", KINDS, ids=[k.name for k in KINDS])
def test_every_kind_declares_owner_and_truth(kind):
    """Law 4 (one owner) and law 2 preserve (file or table truth)."""
    assert kind.truth in ("file", "table")
    if kind.owner_field is None:
        assert kind.notes or any("owner" in g for g in kind.gaps), f"{kind.name}: no owner field and no reason"
    assert set(kind.marks) <= set(MARKS), f"{kind.name}: unknown marks {set(kind.marks) - set(MARKS)}"
    for mark in ("id", "when"):
        assert mark in kind.marks, f"{kind.name}: mark {mark!r} not declared"


def test_declared_gaps_name_the_step_that_closes_them():
    for kind in KINDS:
        for gap in kind.gaps:
            assert re.search(r"step \d", gap), f"{kind.name}: gap without a step: {gap!r}"


def test_rule_of_sight_lives_in_one_place():
    """Law 4: one function decides what a workspace may see; no caller re-implements it."""
    owners = []
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*def visible\(", text, re.M):
            owners.append(path.relative_to(PACKAGE).as_posix())
        # the shape of the rule, re-implemented inline, is the thing we forbid
        if "memory/store.py" not in path.as_posix() and re.search(r'==\s*"shared"', text):
            pytest.fail(f"{path.relative_to(PACKAGE).as_posix()} re-implements the rule of sight")
    assert owners == ["memory/store.py"], owners


def test_memory_search_applies_the_rule_of_sight_everywhere_it_is_called():
    """Every memory search a chat or agent runs passes the workspace through (law 4)."""
    for rel in ("tools/catalog.py", "core/context.py", "memory/extract.py"):
        tree = ast.parse((PACKAGE / rel).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "search"
                 and isinstance(n.func.value, ast.Name | ast.Attribute)
                 and ("mem" in ast.unparse(n.func.value) or "memory" in ast.unparse(n.func.value))
                 and "session" not in ast.unparse(n.func.value)]
        for c in calls:
            kw = {k.arg for k in c.keywords}
            assert "workspace" in kw, f"{rel}: memory search without a workspace: {ast.unparse(c)[:80]}"


def test_no_kind_is_hard_deleted_outside_a_declared_gap():
    """Law 2 (Mahesh): the only deletion is Sachin's explicit, logged act, which lives in a method
    named delete_forever. Stores whose end is still a delete must say so in the registry."""
    allowed = {k.store.partition(":")[0].removeprefix("jarvis.").replace(".", "/") + ".py" for k in KINDS
               if any("delete" in g for g in k.gaps)}
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE).as_posix()
        text = path.read_text(encoding="utf-8")
        # the body of delete_forever is the one place a truth row may go (archived rows only)
        text = re.sub(r"\n    def delete_forever\b.*?(?=\n    def |\nclass |\Z)", "", text, flags=re.S)
        for m in re.finditer(r"DELETE FROM (\w+)", text):
            table = m.group(1)
            # index and cache tables may be rebuilt; truth tables may not be deleted from
            if table in ("tasks", "sched_schedules", "trig_triggers", "reminder_items", "india_wallet",
                         "standing_grants", "sched_pending_approvals", "loka_requests"):
                if rel not in allowed:
                    offenders.append(f"{rel}: DELETE FROM {table}")
    assert offenders == [], offenders


def test_audit_is_append_only():
    """Law 3: Chitragupta's register only grows."""
    text = (PACKAGE / "control" / "audit.py").read_text(encoding="utf-8")
    assert "DELETE" not in text and "unlink" not in text and "truncate" not in text
    assert 'open("a"' in text


def test_registry_knows_the_workspace_kind():
    k = by_name("workspace")
    assert k.end == "archive" and k.truth == "file"
