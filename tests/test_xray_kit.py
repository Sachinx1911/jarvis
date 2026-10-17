"""Phase 9 part F: the REA kit with a fake runner. No node, npm, Chrome or network."""

import json
from pathlib import Path

import pytest

from jarvis.control.audit import AuditLog
from jarvis.xray import XrayError
from jarvis.xray.kit import REA_VERSION, Kit, RunResult

GOOD_REPO = "git+https://github.com/morluto/rea.git"


class FakeRunner:
    """Records every command; answers from a list of (substring-of-argv, RunResult) rules."""

    def __init__(self, rules=None):
        self.rules = list(rules or [])
        self.calls: list[tuple[list[str], float | None, Path | None]] = []

    def __call__(self, argv, timeout, cwd):
        self.calls.append((list(argv), timeout, cwd))
        joined = " ".join(argv)
        for needle, result in self.rules:
            if needle in joined:
                return result
        return RunResult(0, "", "")

    def commands(self):
        return [" ".join(c[0]) for c in self.calls]


def write_installed(root: Path, version: str = REA_VERSION, dep: str | None = None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"dependencies": {"rea-agents": dep or version}}), encoding="utf-8")
    pkg = root / "node_modules" / "rea-agents"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(json.dumps({"name": "rea-agents", "version": version, "bin": {"rea": "bin/rea.js"}}),
                                      encoding="utf-8")
    (pkg / "bin").mkdir(exist_ok=True)
    (pkg / "bin" / "rea.js").write_text("// fake", encoding="utf-8")


def make_kit(tmp_path, runner, which=None, platform="win32", audit=True, is_file=None):
    # Only files under the test folder exist: a developer's real node or Chrome never changes a test.
    in_tmp = lambda p: p.is_file() and tmp_path in p.parents
    return Kit(root=tmp_path / "rea", runner=runner, audit=AuditLog(tmp_path / "audit.jsonl") if audit else None,
               platform=platform, which=which or (lambda name: None), is_file=is_file or in_tmp)


def events(tmp_path):
    path = tmp_path / "audit.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


# ---- install ----

def test_install_never_runs_without_confirm(tmp_path):
    runner = FakeRunner()
    kit = make_kit(tmp_path, runner, which=lambda n: "C:/nodejs/npm.cmd")
    with pytest.raises(XrayError, match="confirmation"):
        kit.install()
    with pytest.raises(XrayError):
        kit.install(confirm=False)
    assert runner.calls == []
    assert [e["event"] for e in events(tmp_path)] == ["xray_install_refused"] * 2
    assert events(tmp_path)[0]["reason"] == "no confirmation"


def test_install_refuses_wrong_repository(tmp_path):
    runner = FakeRunner([("view", RunResult(0, "git+https://github.com/someone-else/rea-agents.git\n", ""))])
    kit = make_kit(tmp_path, runner, which=lambda n: "C:/nodejs/npm.cmd")
    with pytest.raises(XrayError, match="morluto/rea"):
        kit.install(confirm=True)
    assert len(runner.calls) == 1 and "install" not in runner.commands()[0]
    assert runner.calls[0][0][1:] == ["view", "rea-agents@6.5.0", "repository.url"]
    refused = [e for e in events(tmp_path) if e["event"] == "xray_install_refused"]
    assert refused and refused[0]["reason"] == "repository url mismatch"
    assert "someone-else" in refused[0]["repository"]
    assert not (tmp_path / "rea" / "package.json").exists()


def test_install_refuses_when_npm_view_fails(tmp_path):
    runner = FakeRunner([("view", RunResult(1, "", "npm ERR! network"))])
    kit = make_kit(tmp_path, runner, which=lambda n: "/usr/local/bin/npm")
    with pytest.raises(XrayError, match="refused"):
        kit.install(confirm=True)
    assert len(runner.calls) == 1


def test_install_needs_npm(tmp_path):
    runner = FakeRunner()
    kit = make_kit(tmp_path, runner)
    with pytest.raises(XrayError, match="npm was not found"):
        kit.install(confirm=True)
    assert runner.calls == []
    assert events(tmp_path)[-1]["reason"] == "npm not found"


def test_install_pinned_exact_and_no_scripts(tmp_path):
    runner = FakeRunner([("view", RunResult(0, GOOD_REPO + "\n", ""))])
    kit = make_kit(tmp_path, runner, which=lambda n: "C:/nodejs/npm.cmd" if n == "npm" else None)
    summary = kit.install(confirm=True)
    assert "6.5.0" in summary
    assert runner.commands() == [
        "C:/nodejs/npm.cmd view rea-agents@6.5.0 repository.url",
        "C:/nodejs/npm.cmd install rea-agents@6.5.0 --save-exact --ignore-scripts",
    ]
    assert runner.calls[1][2] == tmp_path / "rea"
    pkg = json.loads((tmp_path / "rea" / "package.json").read_text(encoding="utf-8"))
    assert pkg["private"] is True
    done = [e for e in events(tmp_path) if e["event"] == "xray_installed"]
    assert done and done[0]["version"] == "6.5.0" and "morluto/rea" in done[0]["repository"]


def test_install_reports_npm_failure(tmp_path):
    runner = FakeRunner([("view", RunResult(0, GOOD_REPO, "")),
                         ("install", RunResult(1, "", "npm ERR! code E404\nnpm ERR! not found"))])
    kit = make_kit(tmp_path, runner, which=lambda n: "npm")
    with pytest.raises(XrayError, match="E404"):
        kit.install(confirm=True)
    assert events(tmp_path)[-1]["event"] == "xray_install_failed"


# ---- installed / versions ----

def test_installed_requires_exact_version(tmp_path):
    kit = make_kit(tmp_path, FakeRunner())
    assert kit.installed() is False and kit.rea_version() is None
    write_installed(tmp_path / "rea")
    assert kit.installed() is True and kit.rea_version() == "6.5.0"
    write_installed(tmp_path / "rea", version="6.4.0")
    assert kit.installed() is False
    write_installed(tmp_path / "rea", version="6.5.0", dep="^6.5.0")  # a range is not a pin
    assert kit.installed() is False


# ---- finding node and chrome ----

def test_find_node_and_chrome_from_path_then_folders(tmp_path):
    seen = {"node": "/usr/local/bin/node"}
    kit = make_kit(tmp_path, FakeRunner(), which=lambda n: seen.get(n), platform="darwin",
                   is_file=lambda p: p.as_posix() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    assert kit.find_node() == "/usr/local/bin/node"
    assert kit.find_chrome() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    win = make_kit(tmp_path, FakeRunner(), platform="win32",
                   is_file=lambda p: str(p) in (r"C:\Program Files\nodejs\node.exe",
                                                r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
    assert win.find_node() == r"C:\Program Files\nodejs\node.exe"
    assert win.find_chrome() == r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    none = make_kit(tmp_path, FakeRunner(), platform="linux", is_file=lambda p: False)
    assert none.find_node() is None and none.find_chrome() is None


def test_find_npm_next_to_node(tmp_path):
    node_dir = tmp_path / "nodejs"
    node_dir.mkdir()
    (node_dir / "npm.cmd").write_text("", encoding="utf-8")
    kit = make_kit(tmp_path, FakeRunner(), which=lambda n: str(node_dir / "node.exe") if n == "node" else None)
    assert kit.find_npm() == str(node_dir / "npm.cmd")


# ---- diag ----

def test_diag_problems_are_plain_english(tmp_path):
    kit = make_kit(tmp_path, FakeRunner(), is_file=lambda p: False)
    d = kit.diag()
    assert d.ready is False and d.node is None and d.chrome is None and d.rea_version is None
    assert any("Node.js was not found" in p for p in d.problems)
    assert any("Chrome was not found" in p for p in d.problems)
    assert "REA is not installed: run `jarvis xray setup`" in d.problems
    assert d.to_dict()["problems"] == d.problems


def test_diag_ready_and_wrong_versions(tmp_path):
    write_installed(tmp_path / "rea")
    runner = FakeRunner([("--version", RunResult(0, "v24.20.0\n", ""))])
    which = lambda n: {"node": "/opt/homebrew/bin/node", "google-chrome": "/usr/bin/google-chrome"}.get(n)
    kit = make_kit(tmp_path, runner, which=which, platform="linux")
    d = kit.diag()
    assert d.ready is True and d.problems == [] and d.node_version == "24.20.0" and d.rea_version == "6.5.0"

    old = FakeRunner([("--version", RunResult(0, "v20.1.0\n", ""))])
    d = make_kit(tmp_path, old, which=which, platform="linux").diag()
    assert any("too old" in p for p in d.problems)

    write_installed(tmp_path / "rea", version="6.4.0")
    d = make_kit(tmp_path, runner, which=which, platform="linux").diag()
    assert any("6.4.0 is installed but Jarvis needs exactly 6.5.0" in p for p in d.problems)


# ---- running REA ----

def test_rea_runs_cli_with_json_and_parses(tmp_path):
    write_installed(tmp_path / "rea")
    runner = FakeRunner([("inspect-web-page", RunResult(0, "starting...\n{\"title\": \"Demo\", \"n\": 2}\n", ""))])
    kit = make_kit(tmp_path, runner, which=lambda n: "/usr/bin/node" if n == "node" else None, platform="linux")
    out = kit.rea(["inspect-web-page", "--url", "https://demo.test/"])
    assert out == {"title": "Demo", "n": 2}
    argv, timeout, cwd = runner.calls[0]
    assert argv[0] == "/usr/bin/node" and argv[1].endswith("rea.js") and argv[-1] == "--json"
    assert cwd == tmp_path / "rea" and timeout == 120


def test_rea_errors_carry_first_stderr_line(tmp_path):
    write_installed(tmp_path / "rea")
    runner = FakeRunner([("inspect-web-page", RunResult(2, "", "\nError: no browser target on port 9222\n  at main\n"))])
    kit = make_kit(tmp_path, runner, which=lambda n: "node", platform="linux")
    with pytest.raises(XrayError, match="^Error: no browser target on port 9222$"):
        kit.rea(["inspect-web-page"])
    bad = FakeRunner([("inspect-web-page", RunResult(0, "not json at all", ""))])
    with pytest.raises(XrayError, match="did not return JSON"):
        make_kit(tmp_path, bad, which=lambda n: "node", platform="linux").rea(["inspect-web-page"])


def test_rea_without_install_is_a_readable_error(tmp_path):
    kit = make_kit(tmp_path, FakeRunner(), which=lambda n: "node")
    with pytest.raises(XrayError, match="jarvis xray setup"):
        kit.rea(["inspect-web-page"])


def test_flags_are_read_once_from_help(tmp_path):
    write_installed(tmp_path / "rea")
    help_text = "Usage: rea inspect-web-page [options]\n  --url <url>\n  --observation-ms <n>  window\n  --json\n"
    runner = FakeRunner([("--help", RunResult(0, help_text, ""))])
    kit = make_kit(tmp_path, runner, which=lambda n: "node", platform="linux")
    assert kit.has_flag("inspect-web-page", "--observation-ms") is True
    assert kit.has_flag("inspect-web-page", "--include-script-sources") is False
    assert kit.first_flag("inspect-web-page", ("--target-url", "--url")) == "--url"
    assert kit.first_flag("inspect-web-page", ("--nope",)) is None
    assert len(runner.calls) == 1 and runner.calls[0][0][-2:] == ["inspect-web-page", "--help"]
    kit.flags("analyze-web-bundle")
    assert len(runner.calls) == 2
