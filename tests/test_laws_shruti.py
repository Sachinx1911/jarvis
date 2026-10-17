"""The shruti rule (PLAN.md 27.10): no model writes identity or law.

Three checks: the rule itself (which paths are shruti), the two model-facing write doors (the
file tools' path policy and the Coder's code_write) refuse them as T4, and a scan of every write
in the package: no route writes to SOUL.md, config/, prompts/, CLAUDE.md or PLAN.md except the
declared, one-time setup copy of SOUL.md that Sachin's own `jarvis init` performs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.core.shruti import SHRUTI_PATHS, ShrutiError, assert_not_shruti, is_shruti, shruti_reason
from jarvis.db import Store
from jarvis.paths import REPO_ROOT
from jarvis.tools.catalog import ToolDeps, build_registry
from jarvis.tools.code import CodeTools
from jarvis.tools.files import FileTools, PathBlocked, PathPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

PACKAGE = REPO_ROOT / "jarvis"

# What a write to shruti looks like in source: a path built from these names or literals.
SHRUTI_MARKS = ("PROMPTS_DIR", "CONFIG_DIR", "local_config_path", "SOUL.md", "CLAUDE.md", "PLAN.md",
                '"config/', "'config/", '"prompts/', "'prompts/")
WRITE_CALLS = {"write_text", "write_bytes", "copyfile", "copy2", "copy", "rename", "replace", "unlink",
               "rmtree", "safe_dump", "dump"}
# Declared exceptions: Sachin's own acts, not a model route.
ALLOWED_WRITES = {
    "core/runtime.py": "SOUL.example.md",  # jarvis init copies prompts/SOUL.example.md to profile/SOUL.md once, when absent
}


def _examples(home: Path) -> list[Path]:
    return [home / "profile" / "SOUL.md", REPO_ROOT / "config" / "tasks.yaml", REPO_ROOT / "config" / "teams" / "x.yaml",
            REPO_ROOT / "prompts" / "planner.md", REPO_ROOT / "CLAUDE.md", REPO_ROOT / "PLAN.md"]


def test_the_rule_names_identity_law_and_prompts(isolated):
    assert {"profile/SOUL.md", "config/**", "prompts/**", "CLAUDE.md", "PLAN.md"} <= set(SHRUTI_PATHS)
    for p in _examples(isolated):
        assert is_shruti(p), p
        with pytest.raises(ShrutiError):
            assert_not_shruti(p)
    for p in (isolated / "workspace" / "notes.md", isolated / "memory" / "facts" / "m1.md",
              REPO_ROOT / "jarvis" / "core" / "shruti.py", isolated / "profile" / "USER.md",
              REPO_ROOT / "prompts.md", REPO_ROOT / "configs" / "x.yaml"):
        assert shruti_reason(p) is None, p
    assert shruti_reason("relative/config/x.yaml") is None  # relative paths are the caller's policy to resolve
    # case does not save anyone on a case-insensitive disk
    assert is_shruti(REPO_ROOT / "Config" / "Tasks.yaml") and is_shruti(isolated / "PROFILE" / "soul.md")


def test_file_tools_refuse_shruti_as_t4(isolated):
    policy = PathPolicy([isolated, REPO_ROOT])  # even when the whole repo and home are allowed folders
    for p in _examples(isolated):
        with pytest.raises(PathBlocked):
            policy.resolve(str(p))
    assert policy.resolve(str(isolated / "workspace" / "a.md"))
    tools = FileTools(PathPolicy([isolated / "workspace", isolated]))
    with pytest.raises(PathBlocked):
        tools.write_file({"path": "../profile/SOUL.md", "content": "I am someone else"})
    with pytest.raises(PathBlocked):
        tools.overwrite_file({"path": str(isolated / "profile" / "SOUL.md"), "content": "x"})
    with pytest.raises(PathBlocked):
        tools.move_file({"source": "a.md", "destination": "../profile/SOUL.md"})
    assert not (isolated / "profile" / "SOUL.md").exists()


def test_registry_blocks_shruti_before_any_handler_runs(isolated):
    """The precheck of every file tool goes through the path policy: the registry audits the attempt
    as t4_attempt and never calls the handler."""
    store = Store(isolated / "data" / "jarvis.db")
    audit = AuditLog(isolated / "data" / "audit.jsonl")
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit))
    build_registry(reg, ToolDeps(home=isolated, store=store, audit=audit, memory=None, skills=None,
                                 session_id=lambda: "s", max_privacy="P1",
                                 tools_config={"files": {"allowed": [str(isolated)]}}, web=WebClient(),
                                 quarantine=None, tavily_key=lambda: None, system=SystemTools()))
    try:
        target = str(isolated / "profile" / "SOUL.md")
        for name, args in (("write_file", {"path": target, "content": "x"}),
                           ("overwrite_file", {"path": target, "content": "x"}),
                           ("move_file", {"source": "a.md", "destination": target}),
                           ("delete_file", {"path": target}),
                           ("create_docx", {"path": target, "title": "t", "sections": []}),
                           ("create_xlsx", {"path": target, "sheets": []})):
            tool = reg.get(name)
            assert tool is not None and tool.precheck is not None, name
            with pytest.raises(PathBlocked):
                tool.precheck(args)
        for tool in reg.all():  # every tool that writes files has a precheck (the door is never open)
            if tool.writes is not None:
                assert tool.precheck is not None, tool.spec.name
    finally:
        store.close()
    assert "t4_attempt" not in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8") if (
        isolated / "data" / "audit.jsonl").exists() else True


def test_coder_cannot_write_identity_or_law(isolated):
    """A Coder whose project folder is the home (or the Jarvis repo) still cannot touch shruti."""
    code = CodeTools(isolated, {"test_commands": []})
    with pytest.raises(PathBlocked):
        code.code_write({"path": "profile/SOUL.md", "content": "x"})
    assert "Wrote notes/a.md" in code.code_write({"path": "notes/a.md", "content": "ok"})
    repo = CodeTools(REPO_ROOT, {"test_commands": []})
    for rel in ("config/tasks.yaml", "prompts/planner.md", "CLAUDE.md", "PLAN.md"):
        with pytest.raises(PathBlocked):
            repo.code_write({"path": rel, "content": "x"})
    assert (REPO_ROOT / "PLAN.md").read_text(encoding="utf-8").startswith("#")  # untouched


def _write_calls(tree: ast.AST):
    """Every call that writes, with the expression that names its target (receiver or destination)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        target = None
        if name in ("write_text", "write_bytes", "unlink", "rename", "replace", "rmtree", "touch", "mkdir"):
            target = f.value if isinstance(f, ast.Attribute) else None
            if name in ("rename", "replace") and node.args:
                yield name, ast.unparse(node.args[0]), ast.unparse(node)
        elif name in ("copyfile", "copy", "copy2", "move") and len(node.args) > 1:
            target = node.args[1]
        elif name in ("safe_dump", "dump") and len(node.args) > 1:
            target = node.args[1]
        elif name == "open":
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if any(c in mode for c in "wax+"):
                target = f.value if isinstance(f, ast.Attribute) else (node.args[0] if node.args else None)
        if target is not None:
            yield name, ast.unparse(target), ast.unparse(node)


def _assignments(tree: ast.AST) -> dict[str, str]:
    """Simple name -> source of the expression last assigned to it (one level, enough for `soul = ...`)."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.unparse(node.value)
    return out


def test_no_write_path_in_the_package_targets_shruti():
    """Scan every store and tool: no write call's target names a shruti location, except the declared one.
    Reading a prompt or config file to write it somewhere else is fine; the target is what matters."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        text = path.read_text(encoding="utf-8")
        if not any(m in text for m in SHRUTI_MARKS):
            continue
        tree = ast.parse(text)
        names = _assignments(tree)
        for name, target, src in _write_calls(tree):
            expanded = target
            root = target.split(".")[0].split("[")[0].split("(")[0]
            if root in names:  # `soul = home / "profile" / "SOUL.md"; soul.write_text(...)`
                expanded = f"{names[root]} :: {target}"
            if any(m in expanded for m in SHRUTI_MARKS) or any(m.replace('"', "'") in expanded for m in SHRUTI_MARKS):
                if ALLOWED_WRITES.get(rel) and ALLOWED_WRITES[rel] in src:
                    continue
                offenders.append(f"{rel}: {name} -> {target[:60]}  ({src[:80]})")
    assert offenders == [], "\n".join(offenders)


def test_declared_exception_is_a_one_time_setup_copy():
    """The only allowed write to SOUL.md creates it when it is missing (Brahma, by Sachin's init),
    it never overwrites."""
    text = (PACKAGE / "core" / "runtime.py").read_text(encoding="utf-8")
    m = re.search(r"if not soul\.exists\(\):\s*\n\s*shutil\.copyfile\(PROMPTS_DIR / \"SOUL\.example\.md\", soul\)", text)
    assert m, "runtime.py must only copy SOUL.example.md when profile/SOUL.md does not exist"
