"""Coder tools (PLAN.md 9.1, 11.2): typed tools in one project folder, no raw shell.

The Coder works only in <home>/workspace/code/<project>/ (config/coder.yaml).
- code_read (T0): read a file or list the folder.
- code_write (T1): create or replace a file inside the folder; the old version is kept in
  .jarvis-history/. Never inside .git/.
- run_tests (T1): runs ONLY a command from the allowlist in config/coder.yaml, matched exactly
  after shlex.split. shell=False, shell metacharacters refused, minimal environment without
  secrets, per-command timeout that kills the whole process tree, output capped.

Note: tests run the project's own code with the user's rights. The folder and the minimal
environment limit what leaks; they are not an OS sandbox.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import yaml

from jarvis.core.shruti import ShrutiError, assert_not_shruti
from jarvis.paths import CONFIG_DIR, local_config_path
from jarvis.providers.base import ToolSpec
from jarvis.tools.files import PathBlocked, PathDenied, PathPolicy
from jarvis.tools.registry import Tool

PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
SHELL_CHARS = re.compile(r"[;&|<>`$\n\r(){}\[\]*?!~^%\"'\\]")
HISTORY = ".jarvis-history"
SKIP_DIRS = {".git", HISTORY, "node_modules", "__pycache__", ".venv", "venv", ".home", ".tmp", ".pytest_cache"}
MAX_READ_CHARS = 20000
MAX_WRITE_CHARS = 200_000


class CommandRefused(PermissionError):
    pass


def load_coder_config(config_dir: Path = CONFIG_DIR) -> dict:
    def read(p: Path) -> dict:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
        return data if isinstance(data, dict) else {}
    cfg = read(config_dir / "coder.yaml")
    cfg.update(read(local_config_path(config_dir)).get("coder_file") or {})
    return cfg


def project_root(home: Path, project: str, config: dict) -> Path:
    if not PROJECT_RE.fullmatch(project):
        raise ValueError(f"bad project name {project!r} (lowercase letters, digits, - and _)")
    base = Path(config.get("root") or "workspace/code")
    base = base if base.is_absolute() else home / base
    root = base / project
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---- command allowlist ----

def check_command(raw: str, allowed: list[str]) -> list[str]:
    """Return argv for an allowlisted command, or raise CommandRefused."""
    if SHELL_CHARS.search(raw):
        raise CommandRefused("shell characters are not allowed (no pipes, redirects, ';', '&&', quotes, "
                             "variables or wildcards)")
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        raise CommandRefused(f"cannot parse the command: {e}") from e
    if not argv or argv not in [shlex.split(a) for a in allowed]:
        raise CommandRefused(f"not an allowed test command. Allowed: {', '.join(allowed) or '(none)'}")
    return argv


def minimal_env(root: Path, pass_env: list[str] | None = None) -> dict[str, str]:
    """Only what test runners need. No API keys, tokens or JARVIS_* variables."""
    home, tmp = root / ".home", root / ".tmp"
    home.mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    py_dirs = [str(Path(sys.executable).parent)]
    env = {"PATH": os.pathsep.join(py_dirs + [os.environ.get("PATH", "")]), "HOME": str(home), "TMPDIR": str(tmp),
           "TEMP": str(tmp), "TMP": str(tmp), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8", "CI": "1", "NO_COLOR": "1"}
    if sys.platform == "win32":
        for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):  # Windows processes need these
            if k in os.environ:
                env[k] = os.environ[k]
        env["USERPROFILE"] = str(home)
        env["APPDATA"] = str(home / "AppData")
    for name in pass_env or []:
        if name in os.environ and not re.search(r"(key|token|secret|password|auth)", name, re.IGNORECASE):
            env[name] = os.environ[name]
    return env


# ---- process runner ----

@dataclass
class RunResult:
    exit_code: int | None
    output: str
    timed_out: bool
    dropped_chars: int = 0


class ProcessRunner(Protocol):
    def run(self, argv: list[str], cwd: Path, env: dict[str, str], timeout_s: float, max_chars: int) -> RunResult: ...


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the process group made by start_new_session
        except ProcessLookupError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


class SubprocessRunner:
    def run(self, argv: list[str], cwd: Path, env: dict[str, str], timeout_s: float, max_chars: int) -> RunResult:
        exe = shutil.which(argv[0], path=env.get("PATH"))
        if not exe:
            raise CommandRefused(f"{argv[0]} is not installed on this computer")
        kwargs: dict = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                        "stderr": subprocess.STDOUT, "shell": False}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([exe] + argv[1:], **kwargs)
        kept: list[bytes] = []
        size = dropped = 0

        def reader() -> None:
            nonlocal size, dropped
            assert proc.stdout
            for chunk in iter(lambda: proc.stdout.read(4096), b""):  # type: ignore[union-attr]
                room = max_chars - size
                if room > 0:
                    kept.append(chunk[:room])
                    size += min(room, len(chunk))
                dropped += max(0, len(chunk) - max(room, 0))

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            proc.wait(timeout=10)
        t.join(timeout=5)
        text = b"".join(kept).decode("utf-8", errors="replace")
        return RunResult(None if timed_out else proc.returncode, text, timed_out, dropped)


# ---- tools ----

def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


class CodeTools:
    def __init__(self, root: Path, config: dict, runner: ProcessRunner | None = None):
        self.root = root.resolve()
        self.policy = PathPolicy([self.root])
        self.config = config
        self.runner = runner or SubprocessRunner()
        self.commands = [str(c) for c in config.get("test_commands") or []]
        self.last_test: RunResult | None = None  # for the run_tests post-check

    def resolve(self, raw: str) -> Path:
        path = self.policy.resolve(raw or ".")
        rel = path.relative_to(self.root).parts if path != self.root else ()
        if any(p in (".git", HISTORY) for p in rel):
            raise PathDenied(f"{raw} is inside a protected folder (.git, {HISTORY})")
        return path

    def precheck(self, args: dict) -> None:
        if "path" in args:
            self.resolve(args["path"])

    def code_read(self, args: dict) -> str:
        path = self.resolve(args.get("path") or ".")
        if path.is_dir():
            lines = []
            for p in sorted(path.rglob("*")):
                if any(part in SKIP_DIRS for part in p.relative_to(self.root).parts) or not p.is_file():
                    continue
                lines.append(f"- {p.relative_to(self.root).as_posix()} ({p.stat().st_size} bytes)")
                if len(lines) >= 300:
                    lines.append("- ... (more files not shown)")
                    break
            return "\n".join(lines) or "(empty project folder)"
        if not path.is_file():
            return f"No file {args.get('path')}."
        text = path.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + f"\n[... truncated, {len(text)} characters]"

    def code_write(self, args: dict) -> str:
        path = self.resolve(args["path"])
        try:  # shruti (PLAN.md 27.10): the Coder never writes identity, law or prompts, even in the Jarvis repo
            assert_not_shruti(path)
        except ShrutiError as e:
            raise PathBlocked(str(e)) from e
        if path == self.root or path.is_dir():
            return f"{args['path']} is a folder."
        content = args["content"][:MAX_WRITE_CHARS]
        note = ""
        if path.exists():
            hist = self.root / HISTORY
            hist.mkdir(exist_ok=True)
            backup = hist / f"{datetime.now():%Y%m%d-%H%M%S}-{path.name}"
            shutil.copy2(path, backup)
            note = f"; old version kept in {backup.relative_to(self.root).as_posix()}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {path.relative_to(self.root).as_posix()} ({len(content)} characters){note}."

    def verify_write(self, args: dict) -> tuple[bool, str]:
        path = self.resolve(args["path"])
        want = hashlib.sha256(args["content"][:MAX_WRITE_CHARS].encode("utf-8")).hexdigest()
        ok = path.is_file() and hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() == want
        return ok, "file has the expected content" if ok else "file missing or content differs"

    def command_check(self, args: dict) -> None:
        try:
            check_command(args["command"], self.commands)
        except CommandRefused as e:
            raise PathDenied(str(e)) from e

    def run_tests(self, args: dict) -> str:
        argv = check_command(args["command"], self.commands)
        timeout = float(self.config.get("timeout_seconds", 300))
        cap = int(self.config.get("max_output_chars", 20000))
        start = time.monotonic()
        self.last_test = None
        res = self.runner.run(argv, self.root, minimal_env(self.root, self.config.get("pass_env")), timeout, cap)
        self.last_test = res
        took = time.monotonic() - start
        head = (f"TIMED OUT after {timeout:.0f}s; the process tree was killed." if res.timed_out
                else f"Exit code {res.exit_code} ({'passed' if res.exit_code == 0 else 'failed'}) in {took:.1f}s.")
        tail = f"\n[... {res.dropped_chars} more characters of output dropped]" if res.dropped_chars else ""
        return f"{head}\n{res.output}{tail}"

    def verify_tests(self, args: dict) -> tuple[bool, str]:
        """Verify-after-act: the exit code of the process itself, never words in its output."""
        res = self.last_test
        if res is None:
            return False, "no test run recorded"
        if res.timed_out or res.exit_code is None:
            return False, "the test command timed out"
        return res.exit_code == 0, f"test command exited with code {res.exit_code}"


def coder_tools(code: CodeTools) -> list[Tool]:
    S = {"type": "string"}
    where = "Paths are relative to the project folder."
    allowed = ", ".join(code.commands) or "(none configured)"
    return [
        Tool(ToolSpec("code_read", f"Read a file, or list the project when path is empty or a folder. {where}",
                      _obj({"path": S}, [])), "T0", code.code_read, precheck=code.precheck),
        Tool(ToolSpec("code_write", f"Create or replace a file in the project (old version kept). {where}",
                      _obj({"path": S, "content": S}, ["path", "content"])), "T1", code.code_write,
             verify=code.verify_write, precheck=code.precheck),
        Tool(ToolSpec("run_tests", f"Run the project's tests. command must be exactly one of: {allowed}.",
                      _obj({"command": S}, ["command"])), "T1", code.run_tests, precheck=code.command_check,
             verify=code.verify_tests),
    ]
