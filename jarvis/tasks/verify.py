"""Verify-after-act (reports/Personal AI capability gaps.md, item 5).

Agents that fail without noticing are the main real-world agent failure. Jarvis therefore
checks what an agent SAYS it did against what its tools DID, deterministically:

- Operator: each effect claimed in the DONE section of its report must be backed by a
  successful, verified tool run of the matching kind (and, when the claim names a file, page
  or app, a run whose arguments or result mention it). A claimed action with no such run
  fails verification. Effects the tools had but the report does not mention are listed as
  warnings.
- Coder: the project folder is hashed before and after the task; the files the Coder lists
  under CHANGED must be exactly the files that changed. Its last run_tests must have passed,
  after its last code_write.

Everything here reads SQLite rows and files; no model is involved.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

NOT_VERIFIED = "[NOT verified"

# Kind of effect -> (words in a claim line, tools that can produce it). Order matters: the
# first kinds are the more specific ones.
CLAIM_KINDS: list[tuple[str, re.Pattern[str], frozenset[str]]] = [
    ("submit", re.compile(r"\b(submit(ted)?|sent|send|posted|ordered|booked|placed|paid|registered|signed up)\b", re.I),
     frozenset({"browser_submit", "gmail_send"})),
    ("fill", re.compile(r"\b(fill(ed)?|typed|entered)\b", re.I), frozenset({"browser_fill"})),
    ("download", re.compile(r"\bdownload(ed)?\b", re.I), frozenset({"browser_download"})),
    ("screenshot", re.compile(r"\bscreenshots?\b", re.I), frozenset({"browser_screenshot", "browser_submit"})),
    ("click", re.compile(r"\bclick(ed)?\b", re.I), frozenset({"browser_click"})),
    ("open_page", re.compile(r"\b(open(ed)?|visit(ed)?|went to|navigated|load(ed)?)\b[^.\n]*"
                             r"(https?://|www\.|\b[a-z0-9-]+\.[a-z]{2,}\b|\bpage\b|\bsite\b|\bwebsite\b)", re.I),
     frozenset({"browser_open", "web_fetch"})),
    ("open_app", re.compile(r"\b(open(ed)?|launch(ed)?|start(ed)?)\b", re.I), frozenset({"open_app"})),
    ("write", re.compile(r"\b(wrote|written|write|created|saved|made a file)\b", re.I),
     frozenset({"write_file", "overwrite_file", "code_write", "browser_screenshot", "browser_download",
                "browser_submit"})),
    ("move", re.compile(r"\b(moved|renamed)\b", re.I), frozenset({"move_file"})),
    ("delete", re.compile(r"\b(deleted|removed)\b", re.I), frozenset({"delete_file"})),
    ("notify", re.compile(r"\bnotif(y|ied|ication)\b", re.I), frozenset({"notify"})),
]
# Successful runs of these tools change something; the report should mention each.
EFFECT_TOOLS = frozenset({"browser_submit", "browser_fill", "browser_download", "browser_click", "write_file",
                          "overwrite_file", "move_file", "delete_file", "open_app", "notify", "code_write",
                          "gmail_send", "calendar_create_event", "reminder_create"})
SECTION_RE = re.compile(r"^\s*(?:\d+[.)]\s*)?\**\s*(DONE|EVIDENCE|NOT DONE|CHANGED|TESTS|OPEN)\s*\**\s*:\s*(.*)$", re.I)
URL_RE = re.compile(r"https?://[^\s)\]>\"'|,]+")
FILE_RE = re.compile(r"(?<![\w/.-])((?:[\w-]+/)*[\w-]+\.[A-Za-z0-9]{1,5})(?![\w/])")
HOST_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)


@dataclass
class Claim:
    text: str
    kind: str                       # one of CLAIM_KINDS, or "other" (not an action Jarvis can check)
    status: str = "unchecked"       # supported | unsupported | unchecked
    evidence: str = ""              # the tool run that backs it, or why it is not backed

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimReport:
    claims: list[Claim] = field(default_factory=list)
    unreported: list[str] = field(default_factory=list)   # effects the tools had but the report omits
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "claims": [c.as_dict() for c in self.claims],
                "unreported": self.unreported, "problems": self.problems}


# ---- report parsing ----

def report_sections(text: str) -> dict[str, list[str]]:
    """Lines under each header (DONE:, EVIDENCE:, NOT DONE:, CHANGED:, TESTS:, OPEN:).
    Text before any header goes under "": a report without headers is all claims."""
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for raw in text.splitlines():
        m = SECTION_RE.match(raw)
        if m:
            current = m.group(1).upper()
            sections.setdefault(current, [])
            rest = m.group(2).strip()
            if rest:
                sections[current].append(rest)
            continue
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        if line:
            sections.setdefault(current, []).append(line)
    return sections


def claim_lines(text: str) -> list[str]:
    s = report_sections(text)
    lines = s.get("DONE") if "DONE" in s else s.get("", [])
    return [ln for ln in (lines or []) if ln.lower() not in ("none", "nothing", "-", "n/a")]


NEGATION_RE = re.compile(r"\b(not|no|never|nothing|none|unable|cannot|can't|couldn't|didn't|wasn't|won't)\b", re.I)


def classify(line: str) -> list[str]:
    if NEGATION_RE.search(line):
        return ["other"]  # "the form was not sent" claims no effect
    kinds = [kind for kind, rx, _ in CLAIM_KINDS if rx.search(line)]
    if "open_page" in kinds and "open_app" in kinds:
        kinds.remove("open_app")
    if "submit" in kinds and "write" in kinds and not _files_in(line):
        kinds.remove("write")  # "sent the form and saved it" -> the submit
    return kinds or ["other"]


def _files_in(text: str) -> list[str]:
    """File-like tokens (a/b/name.ext); skips abbreviations and numbers such as e.g, 1.5."""
    return [f for f in FILE_RE.findall(text) if len(f.split("/")[-1].split(".")[0]) >= 2
            and f.rsplit(".", 1)[1][:1].isalpha()]


def _objects(line: str) -> list[str]:
    """Things a claim names that a supporting run must mention: hosts, file names."""
    objs: list[str] = []
    for url in URL_RE.findall(line):
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        objs.append(host)
    rest = URL_RE.sub(" ", line)
    for f in _files_in(rest):
        if HOST_RE.fullmatch(f) and not re.search(r"\.(md|txt|py|pdf|csv|png|jpe?g|json|ya?ml|html?|docx?|xlsx?|js|ts)$",
                                                   f, re.I):
            objs.append(f.lower())          # a bare host like shop.example
        else:
            objs.append(f.split("/")[-1].lower())
    return list(dict.fromkeys(objs))


# ---- tool-run evidence ----

@dataclass
class Run:
    id: int
    tool: str
    arguments: str
    result: str
    ok: bool
    agent: str | None = None

    @property
    def verified(self) -> bool:
        """Succeeded, and no post-check said otherwise."""
        return self.ok and NOT_VERIFIED not in (self.result or "")

    def mentions(self, obj: str) -> bool:
        hay = f"{self.arguments}\n{self.result}".lower()
        stem = obj.rsplit(".", 1)[0] if "/" not in obj and obj.count(".") == 1 else obj
        return obj in hay or (len(stem) >= 3 and re.search(rf"\b{re.escape(stem)}\b", hay) is not None)


def tool_runs(conn: sqlite3.Connection, task_id: str, agent: str | None = None) -> list[Run]:
    sql = "SELECT id, tool, arguments, result, ok, agent FROM tool_runs WHERE task_id=?"
    args: tuple = (task_id,)
    if agent:
        sql += " AND agent=?"
        args += (agent,)
    return [Run(r[0], r[1], r[2] or "", r[3] or "", bool(r[4]), r[5]) for r in conn.execute(sql + " ORDER BY id", args)]


def check_claims(report: str, runs: Iterable[Run]) -> ClaimReport:
    runs = list(runs)
    out = ClaimReport()
    used: set[int] = set()
    for line in claim_lines(report):
        objs = _objects(line)
        for kind in classify(line):
            claim = Claim(line, kind)
            out.claims.append(claim)
            if kind == "other":
                claim.evidence = "not an action Jarvis can check"
                continue
            tools = next(t for k, _, t in CLAIM_KINDS if k == kind)
            cands = [r for r in runs if r.tool in tools]
            ok_runs = [r for r in cands if r.verified]
            if objs:  # the claim names a file, site or app: a successful run must mention it
                ok_runs = [r for r in ok_runs if any(r.mentions(o) for o in objs)]
            if ok_runs:
                run = ok_runs[-1]
                used.update(r.id for r in ok_runs)
                claim.status = "supported"
                claim.evidence = f"{run.tool} run #{run.id}" + _verified_note(run)
            else:
                claim.status = "unsupported"
                failed = [r for r in cands if not r.verified]
                claim.evidence = (f"{failed[-1].tool} run #{failed[-1].id} failed or was not verified" if failed
                                  else f"no {'/'.join(sorted(tools))} run")
                out.problems.append(f"claimed but not done: {line[:120]} ({claim.evidence})")
    for r in runs:
        if r.verified and r.tool in EFFECT_TOOLS and r.id not in used:
            out.unreported.append(f"{r.tool} run #{r.id} is not mentioned in the report")
    return out


def _verified_note(run: Run) -> str:
    m = re.search(r"\[verified: ([^\]]+)\]", run.result or "")
    return f" (verified: {m.group(1)[:120]})" if m else ""


# ---- Coder: files changed vs files claimed ----

def folder_hashes(root: Path, skip: Iterable[str]) -> dict[str, str]:
    """relative posix path -> sha256, for every file under root outside the skipped folders."""
    skip = set(skip)
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in skip for part in rel.parts) or not p.is_file():
            continue
        out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed_files(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """path -> created | modified | deleted."""
    out = {}
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            out[path] = "created" if path not in before else "deleted" if path not in after else "modified"
    return out


def claimed_files(report: str) -> set[str]:
    s = report_sections(report)
    lines = s.get("CHANGED") if "CHANGED" in s else s.get("", [])
    files: set[str] = set()
    for line in lines or []:
        for f in _files_in(URL_RE.sub(" ", line)):
            files.add(f.strip("`'\"").lstrip("./"))
    return files


def check_coder(report: str, before: dict[str, str], after: dict[str, str], runs: list[Run]) -> ClaimReport:
    out = ClaimReport()
    changed = changed_files(before, after)
    claimed = claimed_files(report)

    def match(c: str) -> str | None:
        if c in changed:
            return c
        hits = [p for p in changed if p.split("/")[-1] == c.split("/")[-1] and p.endswith(c)]
        return hits[0] if len(hits) == 1 else None

    matched: set[str] = set()
    for c in sorted(claimed):
        m = match(c)
        claim = Claim(f"changed {c}", "write")
        out.claims.append(claim)
        if m:
            matched.add(m)
            claim.status, claim.evidence = "supported", f"{m} {changed[m]} (hash differs before/after)"
        else:
            claim.status, claim.evidence = "unsupported", "file did not change in the project folder"
            out.problems.append(f"the report says {c} changed, but it did not")
    for path, how in changed.items():
        if path not in matched:
            out.problems.append(f"{path} was {how} but the report does not list it")
            out.unreported.append(f"{path} {how}")
    if not claimed and not changed:
        out.claims.append(Claim("no files changed", "other", "unchecked", "nothing to compare"))

    tests = [r for r in runs if r.tool == "run_tests"]
    writes = [r for r in runs if r.tool == "code_write" and r.ok]
    last = tests[-1] if tests else None
    passed = bool(last and last.ok and re.search(r"Exit code 0 \(passed\)", last.result or ""))
    claim = Claim("tests pass", "tests")
    out.claims.append(claim)
    if not last:
        claim.status, claim.evidence = "unsupported", "run_tests was never run"
        out.problems.append("the tests were not run, or the last test run failed")
    elif not passed:
        claim.status, claim.evidence = "unsupported", f"last run_tests (run #{last.id}) did not pass"
        out.problems.append("the tests were not run, or the last test run failed")
    elif writes and writes[-1].id > last.id:
        claim.status, claim.evidence = "unsupported", "code changed after the last test run"
        out.problems.append("code was changed after the last passing test run")
    else:
        claim.status, claim.evidence = "supported", f"run_tests run #{last.id} passed"
    return out
