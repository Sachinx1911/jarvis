"""Teach-by-demonstration (PLAN.md section 8).

Between "start" and "stop" Jarvis collects: the chat with Jarvis and every tool it ran
(already logged), file changes in the allowed folders (before/after snapshot), terminal
commands (a transcript the user starts) and the user's own notes. A model drafts a SKILL.md;
it is saved as a skill only after the user approves it. No mouse or keyboard capture.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from jarvis.db import Store
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import redact_p3
from jarvis.providers.base import LLMRequest, Message, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.schema import validate
from jarvis.tools.files import is_secret_path

MAX_FILE_BYTES = 200_000
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "inputs": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["name", "description"], "additionalProperties": False}},
        "preconditions": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "tool": {"type": "string"}},
            "required": ["text", "tool"], "additionalProperties": False}},
        "verify": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "description", "inputs", "preconditions", "steps", "verify"],
    "additionalProperties": False,
}


def _snapshot(roots: list[Path]) -> dict[str, str]:
    snap: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and ".trash" not in p.parts and not is_secret_path(p) and p.stat().st_size <= MAX_FILE_BYTES:
                snap[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


def terminal_commands(transcript: str) -> list[str]:
    """Commands from a PowerShell Start-Transcript file or a macOS `script` log (best effort)."""
    cmds = []
    for line in transcript.splitlines():
        m = re.match(r"^PS [^>]*>\s*(.+)$", line) or re.match(r"^.*?[%$#]\s+(\S.*)$", line)
        if m and not m.group(1).lower().startswith(("stop-transcript", "exit")):
            cmds.append(redact_p3(m.group(1).strip())[0])
    return cmds


@dataclass
class Recording:
    id: str
    name: str
    folder: Path
    meta: dict[str, Any]


class Recorder:
    def __init__(self, home: Path, store: Store, file_roots: list[Path]):
        self.home = home
        self.store = store
        self.roots = file_roots
        self.dir = home / "data" / "recordings"

    def active(self) -> Recording | None:
        for meta_file in sorted(self.dir.glob("*/meta.json")):
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if meta.get("status") == "recording":
                return Recording(meta["id"], meta["name"], meta_file.parent, meta)
        return None

    def start(self, name: str) -> Recording:
        if self.active():
            raise RuntimeError("a recording is already running (jarvis record stop)")
        rid = "r-" + uuid.uuid4().hex[:6]
        folder = self.dir / rid
        folder.mkdir(parents=True)
        started = self.store.conn.execute("SELECT datetime('now')").fetchone()[0]
        meta = {"id": rid, "name": name, "status": "recording", "started_at": started,
                "snapshot": _snapshot(self.roots), "notes": []}
        (folder / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return Recording(rid, name, folder, meta)

    def terminal_hint(self, rec: Recording) -> str:
        path = rec.folder / "terminal.txt"
        if sys.platform == "win32":
            return f"To record terminal commands, run in PowerShell:  Start-Transcript -Path \"{path}\""
        return f"To record terminal commands, run:  script -q \"{path}\"   (type exit when done)"

    def note(self, text: str) -> None:
        rec = self.active()
        if not rec:
            raise RuntimeError("no recording is running")
        rec.meta["notes"].append(redact_p3(text)[0])
        (rec.folder / "meta.json").write_text(json.dumps(rec.meta, indent=1), encoding="utf-8")

    def stop(self) -> tuple[Recording, str]:
        rec = self.active()
        if not rec:
            raise RuntimeError("no recording is running")
        evidence = self._evidence(rec)
        (rec.folder / "evidence.md").write_text(evidence, encoding="utf-8")
        rec.meta["status"] = "stopped"
        rec.meta.pop("snapshot", None)
        (rec.folder / "meta.json").write_text(json.dumps(rec.meta, indent=1), encoding="utf-8")
        return rec, evidence

    def _evidence(self, rec: Recording) -> str:
        since = rec.meta["started_at"]
        conn = self.store.conn
        out = [f"# Demonstration: {rec.name}", ""]
        msgs = conn.execute("SELECT role, parts FROM messages WHERE ts >= ? ORDER BY id", (since,)).fetchall()
        out.append("## Conversation")
        for role, parts in msgs:
            text = " ".join(p.get("text", "") for p in json.loads(parts) if p.get("type") == "TextPart")
            if text and not text.startswith("/record"):
                out.append(f"- {role}: {redact_p3(text[:600])[0]}")
        runs = conn.execute("SELECT tool, tier, arguments, ok FROM tool_runs WHERE ts >= ? ORDER BY id", (since,)).fetchall()
        out += ["", "## Tools Jarvis ran"]
        out += [f"- {tool} ({tier}) {redact_p3(args)[0][:400]} -> {'ok' if ok else 'failed'}"
                for tool, tier, args, ok in runs] or ["- none"]
        before, after = rec.meta.get("snapshot", {}), _snapshot(self.roots)
        out += ["", "## File changes"]
        changed = False
        for path in sorted(set(before) | set(after)):
            if before.get(path) == after.get(path):
                continue
            changed = True
            p = Path(path)
            kind = "created" if path not in before else "deleted" if path not in after else "modified"
            out.append(f"- {kind}: {self._show(p)}")
            if kind != "deleted" and p.suffix in (".md", ".txt", ".csv", ".json", ".yaml", ".py"):
                out.append("  ```\n  " + redact_p3(p.read_text(encoding="utf-8", errors="replace")[:800])[0]
                           .replace("\n", "\n  ") + "\n  ```")
        if not changed:
            out.append("- none")
        transcript = rec.folder / "terminal.txt"
        out += ["", "## Terminal commands"]
        if transcript.exists():
            cmds = terminal_commands(transcript.read_text(encoding="utf-8", errors="replace"))
            out += [f"- `{c}`" for c in cmds] or ["- none"]
        else:
            out.append("- not recorded")
        from jarvis.browser import browser_steps_evidence  # Phase 8: steps from the isolated browser

        out += ["", browser_steps_evidence(rec.folder)]
        out += ["", "## User's notes"]
        out += [f"- {n}" for n in rec.meta.get("notes", [])] or ["- none"]
        return "\n".join(out) + "\n"

    def _show(self, p: Path) -> str:
        for r in self.roots:
            if p.is_relative_to(r):
                return p.relative_to(r).as_posix()
        return p.name

    # ---- drafting and approval ----

    def draft(self, rec_id: str, provider: ReasoningProvider, decision: RouteDecision,
              tool_tiers: dict[str, str]) -> Path:
        folder = self.dir / rec_id
        evidence = (folder / "evidence.md").read_text(encoding="utf-8")
        path = folder / "SKILL.draft.md"
        path.write_text(draft_skill(evidence, provider, decision, tool_tiers, f"recording {rec_id}"), encoding="utf-8")
        return path

    def approve(self, rec_id: str, skills_dir: Path) -> Path:
        draft = self.dir / rec_id / "SKILL.draft.md"
        if not draft.exists():
            raise FileNotFoundError("no draft for this recording (jarvis record draft)")
        return save_skill(draft.read_text(encoding="utf-8"), skills_dir)


def draft_skill(evidence: str, provider: ReasoningProvider, decision: RouteDecision, tool_tiers: dict[str, str],
                source: str) -> str:
    """Evidence (markdown: conversation, tools run, file changes, notes) -> SKILL.md text.
    Shared by teach-by-demonstration and "do this every time" (jarvis/tasks/repeat.py)."""
    req = LLMRequest(route="skill_draft", model=decision.model,
                     system=(PROMPTS_DIR / "skill_draft.md").read_text(encoding="utf-8"),
                     messages=[Message.text("user", evidence[:20000])], reasoning=decision.effort,  # type: ignore[arg-type]
                     response_schema=DRAFT_SCHEMA)
    res = provider.structured(req, DRAFT_SCHEMA)
    if not res.valid or not validate(res.data, DRAFT_SCHEMA):
        raise ValueError("the model did not return a valid skill draft")
    return render_skill(res.data or {}, tool_tiers, version=1, source=source)


def skill_name(text: str) -> str:
    """The name in a SKILL.md front matter, made safe for a folder name."""
    meta = yaml.safe_load(re.match(r"^---\n(.*?)\n---", text, re.DOTALL).group(1))  # type: ignore[union-attr]
    return re.sub(r"[^a-z0-9-]+", "-", str(meta["name"]).lower()).strip("-") or "skill"


def save_skill(text: str, skills_dir: Path) -> Path:
    """Save an approved SKILL.md. An existing skill of that name is kept as SKILL.v<n>.md."""
    target = skills_dir / skill_name(text) / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():  # keep the old version; the new one gets the next number
        old = yaml.safe_load(re.match(r"^---\n(.*?)\n---", target.read_text(encoding="utf-8"), re.DOTALL).group(1))  # type: ignore[union-attr]
        v = int(old.get("version", 1))
        target.rename(target.parent / f"SKILL.v{v}.md")
        text = re.sub(r"^version: \d+$", f"version: {v + 1}", text, count=1, flags=re.MULTILINE)
    target.write_text(text, encoding="utf-8")
    return target


def render_skill(d: dict[str, Any], tool_tiers: dict[str, str], version: int, source: str) -> str:
    """The risk tier of each step comes from Jarvis's own registry, never from the model.
    source: where the skill came from, e.g. "recording r-1a2b3c" or "task t-004"; a bare id
    is read as a recording id."""
    name = re.sub(r"[^a-z0-9-]+", "-", d["name"].lower()).strip("-")[:50] or "skill"
    origin = source if " " in source else f"recording {source}"
    front = {"name": name, "description": d["description"], "version": version, "source": origin}
    out = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(), "---", "",
           f"# {name}", "", d["description"], ""]
    if d["inputs"]:
        out += ["## Inputs"] + [f"- `{{{i['name']}}}`: {i['description']}" for i in d["inputs"]] + [""]
    if d["preconditions"]:
        out += ["## Preconditions"] + [f"- {p}" for p in d["preconditions"]] + [""]
    out.append("## Steps")
    for n, s in enumerate(d["steps"], 1):
        tool = s.get("tool", "").strip()
        tier = tool_tiers.get(tool)
        tag = f" — tool `{tool}`, tier {tier}" + (" (asks every time)" if tier in ("T2", "T3") else "") if tier else ""
        out.append(f"{n}. {s['text']}{tag}")
    out += ["", "## Verify"] + [f"- {v}" for v in d["verify"]]
    return "\n".join(out) + "\n"
