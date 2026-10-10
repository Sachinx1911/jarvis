"""Browser step recording for teach-by-demonstration (PLAN.md section 8, Phase 8 row).

Every driver action is logged as a step (action, target, value, page) in steps.jsonl. DOM
steps, not mouse coordinates, so a skill survives layout changes. Values of password fields
and of fields that look like secrets are never written; P3 patterns are redacted everywhere.
browser_steps_evidence() renders the steps as a markdown section for the recorder's evidence.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from jarvis.browser.driver import BrowserDriver, DownloadResult, ElementInfo, FormSnapshot
from jarvis.privacy import redact_p3

STEPS_FILE = "browser_steps.jsonl"
NOT_RECORDED = "[secret, not recorded]"
# Field names / autocomplete hints that hold secrets even when the input type is not "password".
SECRET_FIELD = re.compile(r"(pass(word|wd|code)?|pwd|pin|otp|one.?time|cvv|cvc|csc|card.?(number|no)|cc-|"
                          r"security.?code|secret|token|current-password|new-password)", re.IGNORECASE)


def is_secret_field(info: ElementInfo, target: str = "") -> bool:
    return info.type == "password" or any(SECRET_FIELD.search(s) for s in (info.name, info.autocomplete, target) if s)


def active_recording_dir(home: Path) -> Path | None:
    """The folder of the running teach-by-demonstration recording, if any (read-only check of
    jarvis/skills/recorder.py's meta.json files)."""
    for meta_file in sorted((home / "data" / "recordings").glob("*/meta.json")):
        try:
            if json.loads(meta_file.read_text(encoding="utf-8")).get("status") == "recording":
                return meta_file.parent
        except (OSError, json.JSONDecodeError):
            continue
    return None


class RecordingDriver:
    """Wraps any BrowserDriver; logs each action to one or more steps files."""

    def __init__(self, inner: BrowserDriver, sinks: list[Path]):
        self.inner = inner
        self.sinks = sinks
        self.n = 0

    def _log(self, action: str, target: str = "", value: str = "", **extra) -> None:
        self.n += 1
        step = {"n": self.n, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action,
                "target": redact_p3(target)[0], "value": redact_p3(value)[0] if value != NOT_RECORDED else value,
                "url": self._safe_url(), **extra}
        line = json.dumps(step, ensure_ascii=False) + "\n"
        for sink in self.sinks:
            sink.parent.mkdir(parents=True, exist_ok=True)
            with sink.open("a", encoding="utf-8") as f:
                f.write(line)

    def _safe_url(self) -> str:
        try:
            url = self.inner.url()
        except Exception:
            return ""
        return redact_p3(url.split("?")[0])[0]  # query strings can carry personal data

    def start(self, profile_dir: Path | None, allow_navigation: Callable[[str], bool]) -> None:
        self.inner.start(profile_dir, allow_navigation)

    def goto(self, url: str) -> None:
        self.inner.goto(url)
        self._log("open", redact_p3(url.split("?")[0])[0])

    def url(self) -> str:
        return self.inner.url()

    def text(self) -> str:
        return self.inner.text()

    def describe(self, target: str) -> ElementInfo:
        return self.inner.describe(target)

    def title(self) -> str:
        fn = getattr(self.inner, "title", None)
        return fn() if callable(fn) else ""

    def value(self, target: str) -> str | None:
        """Read-back of a field's value, or None when the driver cannot read it."""
        fn = getattr(self.inner, "value", None)
        return fn(target) if callable(fn) else None

    def click(self, target: str) -> None:
        self.inner.click(target)
        self._log("click", target)

    def fill(self, target: str, value: str) -> None:
        try:
            secret = is_secret_field(self.inner.describe(target), target)
        except Exception:
            secret = True  # unknown field: do not risk recording a secret
        self.inner.fill(target, value)
        self._log("fill", target, NOT_RECORDED if secret else value)

    def form(self) -> FormSnapshot | None:
        return self.inner.form()

    def submit(self, button: str | None) -> None:
        self.inner.submit(button)
        self._log("submit", button or "(form)")

    def screenshot(self, path: Path) -> None:
        self.inner.screenshot(path)
        self._log("screenshot", path.name)

    def download(self, target: str, folder: Path) -> DownloadResult:
        res = self.inner.download(target, folder)
        self._log("download", target, filename=res.filename)
        return res

    def close(self) -> None:
        self.inner.close()


def read_steps(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            steps.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return steps


def _steps_file(folder: Path) -> Path:
    for cand in (folder / STEPS_FILE, folder / "browser" / STEPS_FILE):
        if cand.is_file():
            return cand
    return folder / STEPS_FILE


def browser_steps_evidence(task_or_recording_dir: Path | str) -> str:
    """Markdown section for the demonstration evidence (recorder.py), from a recording folder
    or a task folder. Values are already redacted when they are recorded."""
    steps = read_steps(_steps_file(Path(task_or_recording_dir)))
    out = ["## Browser steps"]
    if not steps:
        return "\n".join(out + ["- none"])
    for s in steps:
        where = f" (on {s['url']})" if s.get("url") and s["action"] != "open" else ""
        if s["action"] == "open":
            out.append(f"- open `{s['target']}` - tool `browser_open`")
        elif s["action"] == "fill":
            out.append(f"- fill `{s['target']}` with `{s['value']}`{where} - tool `browser_fill`")
        elif s["action"] == "submit":
            out.append(f"- submit {s['target']}{where} - tool `browser_submit` (T3, asks every time)")
        elif s["action"] == "download":
            out.append(f"- download via `{s['target']}`{where} - tool `browser_download`")
        elif s["action"] == "screenshot":
            out.append(f"- screenshot{where} - tool `browser_screenshot`")
        else:
            out.append(f"- {s['action']} `{s['target']}`{where} - tool `browser_{s['action']}`")
    return "\n".join(out)
