"""The REA kit: node, Chrome and the pinned `rea-agents` package (PLAN.md 18.1 item 1).

REA lives outside the repo in ~/.jarvis-tools/rea, pinned at exactly 6.5.0. It is never
installed on its own: install(confirm=True) first asks npm for the package's repository URL
and refuses unless it points at github.com/morluto/rea. Every process call goes through an
injectable runner so tests never touch node, npm or the network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.xray import XrayError

REA_PACKAGE = "rea-agents"
REA_VERSION = "6.5.0"
REA_REPO = "github.com/morluto/rea"
DEFAULT_ROOT = Path("~/.jarvis-tools/rea")
REA_TIMEOUT = 120.0
SETUP_HINT = "run `jarvis xray setup`"

NODE_CANDIDATES = {
    "win32": [r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe",
              "~/AppData/Roaming/nvm/current/node.exe", "~/scoop/apps/nodejs/current/node.exe"],
    "darwin": ["/opt/homebrew/bin/node", "/usr/local/bin/node", "/opt/local/bin/node", "~/.volta/bin/node",
               "~/.nvm/current/bin/node"],
    "linux": ["/usr/bin/node", "/usr/local/bin/node", "/snap/bin/node", "~/.volta/bin/node"],
}
CHROME_CANDIDATES = {
    "win32": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "~/AppData/Local/Google/Chrome/Application/chrome.exe"],
    "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Chromium.app/Contents/MacOS/Chromium"],
    "linux": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
              "/usr/bin/chromium-browser", "/snap/bin/chromium"],
}
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"]


@dataclass
class RunResult:
    code: int
    stdout: str = ""
    stderr: str = ""


# (argv, timeout seconds, working directory) -> RunResult. Never a shell.
Runner = Callable[[list[str], float | None, Path | None], RunResult]


def subprocess_runner(argv: list[str], timeout: float | None, cwd: Path | None) -> RunResult:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP",
                                                         "APPDATA", "LOCALAPPDATA", "LANG", "COMSPEC", "PATHEXT")}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False, shell=False, env=env, cwd=str(cwd) if cwd else None,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise XrayError(f"{Path(argv[0]).name} took longer than {timeout:.0f} s") from e
    except OSError as e:
        raise XrayError(f"cannot run {Path(argv[0]).name}: {e}") from e
    return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "")


@dataclass
class Diag:
    ready: bool
    node: str | None
    node_version: str | None
    chrome: str | None
    rea_version: str | None
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ready": self.ready, "node": self.node, "node_version": self.node_version, "chrome": self.chrome,
                "rea_version": self.rea_version, "problems": list(self.problems)}


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_json(stdout: str):
    """REA prints JSON with --json; tolerate a log line or two before it."""
    text = (stdout or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        try:
            return json.loads(text[min(starts):])
        except json.JSONDecodeError:
            pass
    raise XrayError("REA did not return JSON" + (f": {_first_line(text)[:120]}" if text else ""))


class Kit:
    def __init__(self, root: Path | None = None, runner: Runner | None = None, audit: AuditLog | None = None,
                 platform: str | None = None, which: Callable[[str], str | None] = shutil.which,
                 is_file: Callable[[Path], bool] | None = None):
        self.root = Path(root).expanduser() if root else DEFAULT_ROOT.expanduser()
        self.runner = runner or subprocess_runner
        self.audit = audit
        self.platform = platform or sys.platform
        self.which = which
        self.is_file = is_file or (lambda p: p.is_file())
        self._flags: dict[str, set[str]] = {}

    def _log(self, event: str, **fields) -> None:
        if self.audit:
            self.audit.write(event, **fields)

    # ---- finding things ----

    def _find(self, names: list[str], candidates: dict[str, list[str]]) -> str | None:
        for name in names:
            found = self.which(name)
            if found:
                return found
        key = "win32" if self.platform.startswith("win") else "darwin" if self.platform == "darwin" else "linux"
        for cand in candidates.get(key, []):
            expanded = os.path.expanduser(cand)
            if self.is_file(Path(expanded)):
                return expanded
        return None

    def find_node(self) -> str | None:
        return self._find(["node"], NODE_CANDIDATES)

    def find_npm(self) -> str | None:
        found = self.which("npm")
        if found:
            return found
        node = self.find_node()
        if node:
            for name in ("npm.cmd", "npm"):
                cand = Path(node).parent / name
                if self.is_file(cand):
                    return str(cand)
        return None

    def find_chrome(self) -> str | None:
        return self._find(CHROME_NAMES, CHROME_CANDIDATES)

    # ---- the installed package ----

    @property
    def package_dir(self) -> Path:
        return self.root / "node_modules" / REA_PACKAGE

    def _read_json(self, path: Path) -> dict | None:
        if not self.is_file(path):
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def rea_version(self) -> str | None:
        pkg = self._read_json(self.package_dir / "package.json")
        return str(pkg.get("version")) if pkg and pkg.get("version") else None

    def installed(self) -> bool:
        """True only when root/package.json pins rea-agents at exactly 6.5.0 and that version is present."""
        root_pkg = self._read_json(self.root / "package.json") or {}
        deps = root_pkg.get("dependencies") or {}
        return deps.get(REA_PACKAGE) == REA_VERSION and self.rea_version() == REA_VERSION

    def rea_entry(self) -> list[str] | None:
        """Command prefix for the REA CLI: `node <bin script>` from the package's "bin" field, so the
        node we found is used even when it is not on PATH; else node_modules/.bin/rea."""
        node = self.find_node()
        pkg = self._read_json(self.package_dir / "package.json")
        if node and pkg:
            bin_field = pkg.get("bin")
            script = bin_field if isinstance(bin_field, str) else (bin_field or {}).get("rea") if isinstance(bin_field, dict) else None
            if script:
                return [node, str(self.package_dir / script)]
        for name in ("rea.cmd", "rea") if self.platform.startswith("win") else ("rea",):
            cand = self.root / "node_modules" / ".bin" / name
            if self.is_file(cand):
                return [str(cand)]
        return None

    # ---- install ----

    def install(self, confirm: bool = False) -> str:
        """Install rea-agents@6.5.0 into the kit root. Runs only with confirm=True, and only after
        `npm view rea-agents repository.url` names github.com/morluto/rea. Returns a one-line summary."""
        if not confirm:
            self._log("xray_install_refused", reason="no confirmation", root=str(self.root))
            raise XrayError(f"installing REA needs your confirmation: {SETUP_HINT}")
        npm = self.find_npm()
        if not npm:
            self._log("xray_install_refused", reason="npm not found", root=str(self.root))
            raise XrayError("npm was not found; install Node.js 22.19+ first (https://nodejs.org)")
        view = self.runner([npm, "view", f"{REA_PACKAGE}@{REA_VERSION}", "repository.url"], REA_TIMEOUT, None)
        repo = _first_line(view.stdout)
        if view.code != 0 or REA_REPO not in repo:
            self._log("xray_install_refused", reason="repository url mismatch", repository=repo[:200],
                      expected=REA_REPO)
            raise XrayError(f"refused: npm says {REA_PACKAGE} comes from {repo or 'an unknown place'!r}, "
                            f"expected {REA_REPO}")
        self.root.mkdir(parents=True, exist_ok=True)
        root_pkg = self.root / "package.json"
        if not self.is_file(root_pkg):
            root_pkg.write_text(json.dumps({"name": "jarvis-rea-kit", "private": True, "dependencies": {}}, indent=2)
                                + "\n", encoding="utf-8")
        res = self.runner([npm, "install", f"{REA_PACKAGE}@{REA_VERSION}", "--save-exact", "--ignore-scripts"],
                          REA_TIMEOUT * 5, self.root)
        if res.code != 0:
            self._log("xray_install_failed", code=res.code, error=_first_line(res.stderr)[:200])
            raise XrayError(f"npm install failed: {_first_line(res.stderr) or f'exit code {res.code}'}")
        self._flags.clear()
        self._log("xray_installed", package=REA_PACKAGE, version=REA_VERSION, root=str(self.root),
                  repository=repo[:200])
        return f"{REA_PACKAGE}@{REA_VERSION} installed in {self.root}"

    # ---- diagnostics ----

    def diag(self) -> Diag:
        problems: list[str] = []
        node = self.find_node()
        node_version = None
        if not node:
            problems.append("Node.js was not found on PATH or in the usual folders: install Node 22.19+ from nodejs.org")
        else:
            try:
                res = self.runner([node, "--version"], 20.0, None)
                node_version = _first_line(res.stdout).lstrip("v") or None
            except XrayError as e:
                problems.append(f"Node.js does not run: {e}")
            if node_version and not self._node_ok(node_version):
                problems.append(f"Node.js {node_version} is too old for REA (needs 22.19+, 24.11+ or 26+)")
        chrome = self.find_chrome()
        if not chrome:
            problems.append("Google Chrome was not found: install it, or set its path in config")
        rea_version = self.rea_version()
        if not self.installed():
            if rea_version:
                problems.append(f"REA {rea_version} is installed but Jarvis needs exactly {REA_VERSION}: {SETUP_HINT}")
            else:
                problems.append(f"REA is not installed: {SETUP_HINT}")
        return Diag(ready=not problems, node=node, node_version=node_version, chrome=chrome,
                    rea_version=rea_version, problems=problems)

    @staticmethod
    def _node_ok(version: str) -> bool:
        m = re.match(r"(\d+)\.(\d+)", version)
        if not m:
            return True  # cannot tell; let REA complain
        major, minor = int(m.group(1)), int(m.group(2))
        return (major == 22 and minor >= 19) or (major == 24 and minor >= 11) or major >= 26

    # ---- running REA ----

    def rea(self, args: list[str], timeout: float = REA_TIMEOUT):
        """Run `rea <args> --json` and return the parsed JSON. Raises XrayError with the first stderr line."""
        entry = self.rea_entry()
        if not entry:
            raise XrayError(f"REA is not installed: {SETUP_HINT}")
        argv = entry + list(args)
        if "--json" not in argv:
            argv.append("--json")
        res = self.runner(argv, timeout, self.root)
        if res.code != 0:
            raise XrayError(_first_line(res.stderr) or _first_line(res.stdout) or f"rea exited with code {res.code}")
        return _parse_json(res.stdout)

    def flags(self, command: str = "inspect-web-page") -> set[str]:
        """The `--flags` that `rea <command> --help` lists, checked once per command and cached.
        Flag names in the pack were not verified against 6.5.0, so nothing depends on them blindly."""
        if command in self._flags:
            return self._flags[command]
        entry = self.rea_entry()
        found: set[str] = set()
        if entry:
            try:
                res = self.runner(entry + [command, "--help"], 30.0, self.root)
                found = set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", res.stdout + "\n" + res.stderr))
            except XrayError:
                found = set()
        self._flags[command] = found
        return found

    def has_flag(self, command: str, flag: str) -> bool:
        return flag in self.flags(command)

    def first_flag(self, command: str, candidates: tuple[str, ...]) -> str | None:
        """The first of `candidates` that this REA build accepts for `command`, or None."""
        known = self.flags(command)
        for flag in candidates:
            if flag in known:
                return flag
        return None
