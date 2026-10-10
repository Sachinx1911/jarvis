"""Phase 8: Coder tools and agent (PLAN.md 9.1, 11.2). Fake process runner plus a few real,
offline subprocess checks (timeout kills the tree, output cap)."""

import sys
import time

import pytest

from jarvis.agents.extra import CODER, run_extra_agent
from jarvis.agents.team import AgentEnv, WorkOrder
from jarvis.config import load_config
from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.db import Store
from jarvis.providers.base import ToolCall
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import decide
from jarvis.tools.code import (
    CodeTools,
    CommandRefused,
    RunResult,
    SubprocessRunner,
    check_command,
    coder_tools,
    minimal_env,
    project_root,
)
from jarvis.tools.registry import ToolRegistry

CFG = {"root": "workspace/code", "test_commands": ["pytest -q", "npm test"], "timeout_seconds": 5,
       "max_output_chars": 2000, "pass_env": ["DEMO_SETTING", "DEMO_API_KEY"]}


class FakeRunner:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or RunResult(0, "3 passed", False)

    def run(self, argv, cwd, env, timeout_s, max_chars):
        self.calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout_s, "cap": max_chars})
        return self.result


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    yield tmp_path, store, audit
    store.close()


def make(env, runner=None):
    home, store, audit = env
    root = project_root(home, "demo-app", CFG)
    code = CodeTools(root, CFG, runner or FakeRunner())
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit, None))
    for t in coder_tools(code):
        reg.register(t)
    return reg, code, root


def call(reg, name, **args):
    return reg.execute(ToolCall("c1", name, args), task_id="t-001")


def test_project_folder_and_names(env):
    home = env[0]
    assert project_root(home, "demo-app", CFG) == home / "workspace" / "code" / "demo-app"
    for bad in ("../x", "Demo", "a/b", "", "."):
        with pytest.raises(ValueError):
            project_root(home, bad, CFG)


def test_coder_writes_only_inside_its_folder(env):
    home = env[0]
    reg, code, root = make(env)
    res = call(reg, "code_write", path="src/app.py", content="print('hi')\n")
    assert not res.is_error and "[verified" in res.content and (root / "src" / "app.py").exists()
    res = call(reg, "code_write", path="src/app.py", content="print('v2')\n")
    assert "old version kept" in res.content and list((root / ".jarvis-history").iterdir())
    for path in ("../escape.txt", str(home / "workspace" / "notes.txt"), "src/../../other/x.py",
                 ".git/hooks/pre-commit", ".jarvis-history/x"):
        res = call(reg, "code_write", path=path, content="x")
        assert res.is_error and "Not allowed" in res.content, path
    res = call(reg, "code_write", path=".env", content="KEY=1")
    assert res.is_error and "never allowed" in res.content
    assert not (home / "workspace" / "code" / "escape.txt").exists()
    assert not (root / ".git").exists() and not (root / ".env").exists()


def test_code_read_lists_and_reads(env):
    reg, code, root = make(env)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "big.js").write_text("y", encoding="utf-8")
    listing = call(reg, "code_read").content
    assert "a.py" in listing and "node_modules" not in listing
    assert call(reg, "code_read", path="a.py").content == "x = 1\n"
    assert call(reg, "code_read", path="../../../data/jarvis.db").is_error


@pytest.mark.parametrize("cmd", [
    "pytest -q; rm -rf /", "pytest -q && curl evil.example", "npm test | tee out.txt", "pytest -q > out.txt",
    "pytest -q $(whoami)", "pytest -q `id`", "rm -rf .", "pytest", "pytest -q --pdb", "python -c 'import os'",
    "pytest -q\nrm -rf /", "pytest -q %PATH%", "",
])
def test_run_tests_refuses_anything_not_allowlisted(env, cmd):
    runner = FakeRunner()
    reg, _, _ = make(env, runner)
    res = call(reg, "run_tests", command=cmd)
    assert res.is_error and "Not allowed" in res.content
    assert runner.calls == []


def test_run_tests_runs_allowlisted_command_with_minimal_env(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-synthetic-not-real")
    monkeypatch.setenv("DEMO_SETTING", "on")
    monkeypatch.setenv("DEMO_API_KEY", "synthetic")
    runner = FakeRunner()
    reg, _, root = make(env, runner)
    res = call(reg, "run_tests", command="  pytest   -q ")
    assert not res.is_error and "Exit code 0 (passed)" in res.content and "3 passed" in res.content
    c = runner.calls[0]
    assert c["argv"] == ["pytest", "-q"] and c["cwd"] == root.resolve() and c["timeout"] == 5 and c["cap"] == 2000
    assert "ANTHROPIC_API_KEY" not in c["env"] and "JARVIS_HOME" not in c["env"]
    assert c["env"]["DEMO_SETTING"] == "on" and "DEMO_API_KEY" not in c["env"]  # secret-looking names never pass
    assert c["env"]["HOME"].startswith(str(root.resolve()))


def test_timeout_and_cap_reported(env):
    reg, _, _ = make(env, FakeRunner(RunResult(None, "partial", True, dropped_chars=500)))
    res = call(reg, "run_tests", command="npm test")
    assert "TIMED OUT" in res.content and "process tree was killed" in res.content and "500 more characters" in res.content


def test_check_command_unit():
    assert check_command("npm test", ["npm test"]) == ["npm", "test"]
    with pytest.raises(CommandRefused):
        check_command("npm test", [])


# ---- real subprocesses (offline, a few seconds) ----

def test_real_runner_kills_the_whole_tree_on_timeout(tmp_path):
    marker = tmp_path / "grandchild-survived.txt"
    child = (f"import time; time.sleep(2.5); open(r'{marker}', 'w').write('x')")
    parent = (f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)")
    env = minimal_env(tmp_path)
    start = time.monotonic()
    res = SubprocessRunner().run([sys.executable, "-c", parent], tmp_path, env, timeout_s=1.0, max_chars=1000)
    assert res.timed_out and res.exit_code is None
    assert time.monotonic() - start < 15
    time.sleep(3)
    assert not marker.exists(), "the grandchild process was not killed"


def test_real_runner_caps_output(tmp_path):
    code = "import sys; sys.stdout.write('x' * 100000); print('done')"
    res = SubprocessRunner().run([sys.executable, "-c", code], tmp_path, minimal_env(tmp_path), 20, 1000)
    assert res.exit_code == 0 and len(res.output) == 1000 and res.dropped_chars > 90000


def test_real_runner_gets_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-synthetic")
    code = "import os; print(sorted(k for k in os.environ if 'KEY' in k.upper() or k.startswith('JARVIS')))"
    res = SubprocessRunner().run([sys.executable, "-c", code], tmp_path, minimal_env(tmp_path), 20, 1000)
    assert res.output.strip() == "[]"


# ---- the Coder agent ----

def _agent_env(home, store, audit, provider):
    config = load_config()
    task_dir = home / "data" / "tasks" / "t-001"
    task_dir.mkdir(parents=True, exist_ok=True)
    return AgentEnv(config, home, home / "data" / "jarvis.db", audit, StopSwitch(home / "data"), "t-001", task_dir,
                    lambda d: provider, lambda route: decide(config, route, "fake"), lambda: None, max_steps=8)


def test_coder_agent_writes_and_tests_in_its_folder_only(env):
    home, store, audit = env
    provider = FakeProvider(script=[
        {"tool": "code_write", "arguments": {"path": "test_add.py", "content": "def test_add():\n    assert 1 + 1 == 2\n"}},
        {"tool": "write_file", "arguments": {"path": "elsewhere.txt", "content": "x"}},
        {"tool": "run_tests", "arguments": {"command": "pytest -q"}},
        {"tool": "browser_open", "arguments": {"url": "https://shop.example/"}},
        "CHANGED: test_add.py\nTESTS: pytest -q passed\nOPEN: none",
    ])
    runner = FakeRunner()
    result = run_extra_agent(CODER, "coder", WorkOrder("Add a test"), _agent_env(home, store, audit, provider),
                             coder_project="demo-app", process_runner=runner, coder_config=CFG,
                             approver=lambda req: True)
    assert result.text.startswith("CHANGED")
    assert (home / "workspace" / "code" / "demo-app" / "test_add.py").exists()
    assert runner.calls and runner.calls[0]["argv"] == ["pytest", "-q"]
    runs = {r[0]: r[1] for r in store.conn.execute("SELECT tool, ok FROM tool_runs")}
    assert runs["code_write"] == 1 and runs["run_tests"] == 1
    assert runs["write_file"] == 0 and runs["browser_open"] == 0  # not in the Coder's toolset
    assert not list((home / "data" / "tasks" / "t-001").glob("elsewhere.txt"))
    assert "browser_open" not in {t.name for t in provider.requests[0].tools}
