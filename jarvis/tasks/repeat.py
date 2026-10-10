""""Do this every time" (PROGRESS.md, Next step 3, Automation).

After a task (or a chat action) completes successfully, Jarvis can turn it into automation:
a skill drafted from the evidence (goal, plan, tool runs, outputs) with the recorder's draft
path, plus a schedule read by the proactive schedule parser. Both are shown first and saved
only after an explicit yes (PLAN.md: nothing standing is created without Sachin).

It also notices repetition: when the same kind of task ran 3 times in 30 days (normalized
goal words, Jaccard similarity), the receipt suggests "Make this automatic?".

Proposals waiting for a yes live in <home>/data/repeat/pending/<id>.json; saved automations
are listed in <home>/data/repeat/saved.jsonl (so the hint stops once a task is automated).
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jarvis.privacy import redact_p3
from jarvis.providers.base import ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.skills.recorder import draft_skill, save_skill, skill_name
from jarvis.tasks.store import Task, TaskStore

if TYPE_CHECKING:
    from jarvis.proactive.schedule_parse import ScheduleDraft, ScheduleParser

WINDOW_DAYS = 30
MIN_RUNS = 3
SIMILAR = 0.6
EXAMPLE_WHEN = "every Monday at 9"
STOPWORDS = frozenset("""a an the and or of for to in on at by with from into about me my mine our your you
please pls kindly can could would will shall should do does did make give get tell show find let i we it is are
be this that these those some any all new now today tomorrow yesterday week weekly daily month monthly year
again also just then than as so up out sir jarvis""".split())
_MONTHS = frozenset("jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july "
                    "august september october november december".split())
_DAYS = frozenset("mon tue wed thu fri sat sun monday tuesday wednesday thursday friday saturday sunday".split())


class RepeatError(ValueError):
    """Why this cannot be turned into automation (shown to the user as is)."""


# ---- repetition ----

def goal_words(goal: str) -> frozenset[str]:
    """Normalized content words of a goal: lowercase, no numbers, dates, links or filler."""
    text = re.sub(r"https?://(?:www\.)?([^/\s]+)\S*", r" \1 ", goal.lower())
    out = set()
    for w in re.findall(r"[a-zऀ-ॿ]+", text):
        if len(w) < 2 or w in STOPWORDS or w in _MONTHS or w in _DAYS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # laptops -> laptop
        out.add(w)
    return frozenset(out)


def similarity(a: str | frozenset[str], b: str | frozenset[str]) -> float:
    x = a if isinstance(a, frozenset) else goal_words(a)
    y = b if isinstance(b, frozenset) else goal_words(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def similar_tasks(tasks: TaskStore, task: Task, days: int = WINDOW_DAYS, threshold: float = SIMILAR) -> list[str]:
    """Ids of tasks that ran (completed or failed) in the last `days` days with a goal like
    this one, including the task itself."""
    words = goal_words(task.goal)
    rows = tasks.db.execute(
        "SELECT id, goal FROM tasks WHERE state IN ('COMPLETED', 'FAILED') AND created_at >= datetime('now', ?) "
        "ORDER BY id", (f"-{int(days)} days",)).fetchall()
    return [tid for tid, goal in rows if tid == task.id or similarity(words, goal_words(goal)) >= threshold]


def repetition_hint(tasks: TaskStore, task: Task) -> str | None:
    """The receipt's "Make this automatic?" line, or None."""
    if task.state != "COMPLETED":
        return None
    ids = similar_tasks(tasks, task)
    if len(ids) < MIN_RUNS:
        return None
    if RepeatStore(tasks.tasks_dir.parent).automated_like(task.goal):
        return None
    return (f"Make this automatic? This kind of task ran {len(ids)} times in the last {WINDOW_DAYS} days "
            f"({', '.join(ids[-5:])}). In chat: /repeat {EXAMPLE_WHEN}  - or: jarvis task repeat {task.id} "
            f"\"{EXAMPLE_WHEN}\". Nothing is saved until you say yes.")


# ---- evidence (same shape as the recorder's demonstration evidence) ----

def _clip(text: str, n: int) -> str:
    return redact_p3((text or "")[:n])[0]


def task_evidence(conn: sqlite3.Connection, tasks: TaskStore, task: Task) -> str:
    """Goal, plan, tool runs and output of a completed task, as markdown for the skill drafter."""
    out = [f"# Completed task to repeat: {task.title}", "", "## Conversation", f"- user: {_clip(task.goal, 600)}"]
    plan = task.plan or {}
    if plan:
        out += ["", "## Plan", f"- mode: {plan.get('mode') or ('team' if plan.get('use_team') else 'solo')}"]
        out += [f"- research: {r.get('objective', '')} ({r.get('focus', '')})" for r in plan.get("research", [])]
        if plan.get("solo_instructions"):
            out.append(f"- instructions: {_clip(plan['solo_instructions'], 400)}")
        out += [f"- acceptance: {c}" for c in plan.get("acceptance_criteria", [])]
        deliverable = plan.get("deliverable") or {}
        if deliverable:
            out.append(f"- deliverable: {deliverable.get('filename', '')} - {deliverable.get('outline', '')}")
    runs = conn.execute("SELECT agent, tool, tier, arguments, ok FROM tool_runs WHERE task_id=? ORDER BY id",
                        (task.id,)).fetchall()
    out += ["", "## Tools Jarvis ran"]
    out += [f"- {agent or 'jarvis'}: {tool} ({tier}) {_clip(args, 300)} -> {'ok' if ok else 'failed'}"
            for agent, tool, tier, args, ok in runs] or ["- none"]
    folder = tasks.folder(task.id)
    report = (task.checkpoint or {}).get("report")
    out += ["", "## Output"]
    if report and (folder / report).is_file():
        out += [f"- file {report}:", "  ```", "  " + _clip((folder / report).read_text(encoding="utf-8"), 1500)
                .replace("\n", "\n  "), "  ```"]
    else:
        out.append("- none")
    from jarvis.browser import browser_steps_evidence

    out += ["", browser_steps_evidence(folder)]
    return "\n".join(out) + "\n"


@dataclass
class ChatAction:
    session_id: str
    goal: str
    evidence: str
    ts: str


def chat_evidence(conn: sqlite3.Connection, session_id: str) -> ChatAction:
    """The last finished chat action of a session (its last user turn, Jarvis's reply and the
    tools it ran). Raises RepeatError when there is none or a tool failed."""
    rows = conn.execute("SELECT id, ts, role, parts FROM messages WHERE session_id=? ORDER BY id",
                        (session_id,)).fetchall()

    def text_of(parts: str) -> str:
        try:
            return " ".join(p.get("text", "") for p in json.loads(parts) if p.get("type") == "TextPart").strip()
        except (json.JSONDecodeError, AttributeError):
            return ""

    last = None
    for i, (mid, ts, role, parts) in enumerate(rows):
        t = text_of(parts)
        if role == "user" and t and not t.startswith("/"):
            last = i
    if last is None:
        raise RepeatError("Nothing to repeat yet: ask Jarvis to do something first, then /repeat <when>.")
    _, ts, _, parts = rows[last]
    goal = text_of(parts)
    replies = [text_of(p) for _, _, role, p in rows[last + 1:] if role == "assistant" and text_of(p)]
    if not replies:
        raise RepeatError("The last request has no answer yet, so it cannot be repeated.")
    runs = conn.execute("SELECT tool, tier, arguments, ok FROM tool_runs WHERE task_id=? AND ts >= ? ORDER BY id",
                        (session_id, ts)).fetchall()
    if any(not ok for *_, ok in runs):
        raise RepeatError("The last action did not fully succeed (a tool failed or was refused); "
                          "only a successful action can be made automatic.")
    out = ["# Chat action to repeat", "", "## Conversation", f"- user: {_clip(goal, 600)}"]
    out += [f"- assistant: {_clip(r, 600)}" for r in replies]
    out += ["", "## Tools Jarvis ran"]
    out += [f"- {tool} ({tier}) {_clip(args, 300)} -> ok" for tool, tier, args, _ in runs] or ["- none"]
    return ChatAction(session_id, goal, "\n".join(out) + "\n", ts)


# ---- proposals ----

@dataclass
class RepeatProposal:
    id: str
    source: str          # "task t-004" or "chat <session id>"
    goal: str
    when: str
    skill_text: str
    skill: str           # skill name (folder under skills/)
    schedule: dict[str, Any]   # ScheduleDraft fields
    session_id: str = ""
    created_at: str = ""

    def schedule_draft(self) -> "ScheduleDraft":
        from jarvis.proactive.schedule_parse import ScheduleDraft

        return ScheduleDraft(**self.schedule)

    def show(self, now: datetime | None = None, skills_dir: Path | None = None) -> str:
        lines = [f"Automation from {self.source}: {self.goal[:100]}", "", "--- SKILL.md draft ---",
                 self.skill_text.rstrip(), "--- end of draft ---", "", self.schedule_draft().show(now)]
        if skills_dir is not None and (skills_dir / self.skill / "SKILL.md").exists():
            lines.append(f"Note: a skill named {self.skill} exists; it will be kept as an older version.")
        return "\n".join(lines)


def build_proposal(evidence: str, goal: str, source: str, when: str, *, provider: ReasoningProvider,
                   decision: RouteDecision, tool_tiers: dict[str, str], parser: "ScheduleParser",
                   defaults: dict[str, Any] | None = None, session_id: str = "") -> RepeatProposal:
    """Read the schedule first (cheap, may ask a question), then draft the skill."""
    from jarvis.proactive.schedule_parse import ScheduleParseError

    when = when.strip()
    if not when:
        raise RepeatError(f"Say when, e.g. /repeat {EXAMPLE_WHEN}")
    try:
        sched = parser.parse(when, {"kind": "skill", "target": "pending", **(defaults or {})})
    except ScheduleParseError as e:
        raise RepeatError(e.question) from None
    note = (f"\n## User's notes\n- Do this again automatically, {when}. Values that change between runs "
            f"(dates, latest numbers) are inputs, not fixed text.\n")
    try:
        text = draft_skill(evidence + note, provider, decision, tool_tiers, source)
    except ValueError as e:
        raise RepeatError(f"Could not draft the skill: {e}") from None
    name = skill_name(text)
    extra = sched.input.strip() if sched.input.strip().lower() != when.lower() else ""
    sched = replace(sched, name=name[:40], target=name, input=extra)
    return RepeatProposal("rp-" + uuid.uuid4().hex[:6], source, goal, when, text, name, asdict(sched),
                          session_id, datetime.now().isoformat(timespec="seconds"))


class RepeatStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "repeat"
        self.pending_dir = self.dir / "pending"
        self.saved_file = self.dir / "saved.jsonl"

    def put(self, p: RepeatProposal) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        (self.pending_dir / f"{p.id}.json").write_text(json.dumps(asdict(p), ensure_ascii=False, indent=1),
                                                       encoding="utf-8")

    def get(self, pid: str) -> RepeatProposal | None:
        path = self.pending_dir / f"{pid}.json"
        if not re.fullmatch(r"rp-[0-9a-f]{6}", pid) or not path.is_file():
            return None
        return RepeatProposal(**json.loads(path.read_text(encoding="utf-8")))

    def latest(self, session_id: str | None = None) -> RepeatProposal | None:
        items = []
        for path in self.pending_dir.glob("rp-*.json"):
            try:
                p = RepeatProposal(**json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                continue
            if session_id is None or p.session_id == session_id:
                items.append((path.stat().st_mtime, p.created_at, p))
        return max(items, key=lambda x: (x[0], x[1]))[2] if items else None

    def drop(self, pid: str) -> None:
        (self.pending_dir / f"{pid}.json").unlink(missing_ok=True)

    def saved(self) -> list[dict[str, Any]]:
        if not self.saved_file.is_file():
            return []
        out = []
        for line in self.saved_file.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def automated_like(self, goal: str) -> bool:
        words = goal_words(goal)
        return any(similarity(words, frozenset(s.get("words") or [])) >= SIMILAR for s in self.saved())

    def mark_saved(self, p: RepeatProposal, skill_path: Path, schedule_id: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        entry = {"proposal": p.id, "source": p.source, "skill": p.skill, "skill_path": str(skill_path),
                 "schedule_id": schedule_id, "when": p.when, "words": sorted(goal_words(p.goal)),
                 "saved_at": datetime.now().isoformat(timespec="seconds")}
        with self.saved_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.drop(p.id)


def save_proposal(p: RepeatProposal, store: RepeatStore, skills_dir: Path, conn: sqlite3.Connection,
                  now: datetime, grace_s: int, audit=None):
    """Called only after the user said yes. Saves the skill, then the schedule
    (jarvis.proactive.scheduler.ScheduleStore, source "repeat")."""
    from jarvis.proactive.scheduler import ScheduleStore

    draft = p.schedule_draft()
    path = save_skill(p.skill_text, skills_dir)
    schedule = ScheduleStore(conn).add(replace(draft, target=skill_name(p.skill_text)), now, grace_s, "repeat")
    store.mark_saved(p, path, schedule.id)
    if audit is not None:
        audit.write("automation_saved", proposal=p.id, source=p.source, skill=str(path), schedule_id=schedule.id,
                    cron=schedule.cron)
    return path, schedule
