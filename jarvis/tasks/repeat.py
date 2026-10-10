"""Repeat-this (PROGRESS.md "Next step" 2; PLAN.md 8 and 10.3).

`/repeat <when>` (terminal chat, Telegram) and `jarvis task repeat <task-id> <when>` turn a
finished task or the last chat action into automation: a skill drafted from the evidence
(goal, plan, tool runs, output) with the recorder's draft path, plus a schedule read by the
proactive schedule parser. Both are SHOWN first and saved only after an explicit yes from
Sachin on that shown draft (PLAN.md: nothing standing is created without him). A draft that
is not confirmed within PENDING_TTL_S expires.

Scheduled runs of the skill are unattended and keep the scheduler's rule: only T0/T1 actions
run; anything T2+ is refused, queued for approval and listed in the run's receipt
(jarvis/proactive/scheduler.py). The draft says up front which steps that will hit.

It also notices repetition: when the same kind of task ran 3 times in 30 days (normalized
goal words, Jaccard similarity), the receipt suggests "Make this automatic?".

Proposals waiting for a yes live in <home>/data/repeat/pending/<id>.json; saved automations
are listed in <home>/data/repeat/saved.jsonl (so the hint stops once a task is automated).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jarvis.privacy import redact_p3
from jarvis.providers import make_provider
from jarvis.providers.base import ReasoningProvider
from jarvis.routing.policy import RouteDecision, decide
from jarvis.skills.recorder import draft_skill, save_skill, skill_name
from jarvis.tasks.store import Task, TaskStore

if TYPE_CHECKING:
    from jarvis.proactive.schedule_parse import ScheduleDraft, ScheduleParser

WINDOW_DAYS = 30
MIN_RUNS = 3
SIMILAR = 0.6
EXAMPLE_WHEN = "every Monday at 9"
PENDING_TTL_S = 3600            # a draft not confirmed within an hour can no longer be saved
MIN_INTERVAL_MINUTES = 30       # default; config/proactive.yaml schedules.repeat_min_interval_minutes
YES_WORDS = frozenset({"yes", "y", "save", "ho", "हो"})
NO_WORDS = frozenset({"no", "n", "cancel", "nako", "नको"})
TASK_ID_RE = re.compile(r"t-\d{1,6}")
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
            f"({', '.join(ids[-5:])}). In chat or Telegram: /repeat {task.id} {EXAMPLE_WHEN}  - or: "
            f"jarvis task repeat {task.id} \"{EXAMPLE_WHEN}\". Nothing is saved until you say yes.")


def split_task_id(text: str) -> tuple[str | None, str]:
    """"t-004 every Monday at 9" -> ("t-004", "every Monday at 9"); no leading id -> (None, text)."""
    first, _, rest = text.strip().partition(" ")
    if TASK_ID_RE.fullmatch(first.lower()):
        return first.lower(), rest.strip()
    return None, text.strip()


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

_STEP_TIER_RE = re.compile(r"^(\d+)\. (.*?) — tool `([^`]+)`, tier (T[0-4])", re.MULTILINE)


def unattended_steps(skill_text: str) -> list[str]:
    """Steps of a drafted skill that an unattended run may not do (tier T2+, from Jarvis's
    registry): they will be refused and queued for approval."""
    return [f"{n}. {text} ({tool}, {tier})" for n, text, tool, tier in _STEP_TIER_RE.findall(skill_text)
            if tier not in ("T0", "T1")]


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
    created_ts: float = field(default=0.0)   # wall clock (time.time()) for the expiry

    def schedule_draft(self) -> "ScheduleDraft":
        from jarvis.proactive.schedule_parse import ScheduleDraft

        return ScheduleDraft(**self.schedule)

    def expired(self, ttl_s: float = PENDING_TTL_S) -> bool:
        return time.time() - float(self.created_ts or 0) > ttl_s

    def show(self, now: datetime | None = None, skills_dir: Path | None = None) -> str:
        lines = [f"Automation from {self.source}: {self.goal[:100]}", "", "--- SKILL.md draft ---",
                 self.skill_text.rstrip(), "--- end of draft ---", "", self.schedule_draft().show(now)]
        held = unattended_steps(self.skill_text)
        if held:
            lines.append("These steps need approval, so scheduled runs will NOT do them on their own; each time "
                         "they are refused, queued for you (/approvals) and listed in the run's receipt:")
            lines += [f"  {h}" for h in held]
        if skills_dir is not None and (skills_dir / self.skill / "SKILL.md").exists():
            lines.append(f"Note: a skill named {self.skill} exists; it will be kept as an older version.")
        lines.append("Nothing is saved until you confirm this draft.")
        return "\n".join(lines)


def _min_gap_minutes(cron: str, tz: str, now: datetime) -> float | None:
    from jarvis.proactive.schedule_parse import next_runs

    runs = next_runs(cron, tz, now, 6)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(runs, runs[1:])]
    return min(gaps) if gaps else None


def build_proposal(evidence: str, goal: str, source: str, when: str, *, provider: ReasoningProvider,
                   decision: RouteDecision, tool_tiers: dict[str, str], parser: "ScheduleParser",
                   defaults: dict[str, Any] | None = None, session_id: str = "", now: datetime | None = None,
                   min_interval_minutes: float = MIN_INTERVAL_MINUTES) -> RepeatProposal:
    """Read the schedule first (cheap, may ask a question, refuses too-frequent runs), then
    draft the skill. Nothing is stored here."""
    from jarvis.proactive.schedule_parse import ScheduleParseError

    when = when.strip()
    if not when:
        raise RepeatError(f"Say when, e.g. /repeat {EXAMPLE_WHEN}")
    try:
        sched = parser.parse(when, {"kind": "skill", "target": "pending", **(defaults or {})})
    except ScheduleParseError as e:
        raise RepeatError(e.question) from None
    gap = _min_gap_minutes(sched.cron, sched.timezone, now or datetime.now().astimezone())
    if gap is not None and gap < min_interval_minutes:
        raise RepeatError(f"That would run every {gap:.0f} minutes ({sched.cron}). Automations run at most every "
                          f"{min_interval_minutes:.0f} minutes, because each unattended run uses model calls. "
                          f"Try e.g. 'every hour' or '{EXAMPLE_WHEN}'.")
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
                          session_id, datetime.now().isoformat(timespec="seconds"), time.time())


class RepeatStore:
    def __init__(self, data_dir: Path, ttl_s: float = PENDING_TTL_S):
        self.dir = data_dir / "repeat"
        self.pending_dir = self.dir / "pending"
        self.saved_file = self.dir / "saved.jsonl"
        self.ttl_s = ttl_s

    def put(self, p: RepeatProposal) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        (self.pending_dir / f"{p.id}.json").write_text(json.dumps(asdict(p), ensure_ascii=False, indent=1),
                                                       encoding="utf-8")

    def _load(self, path: Path) -> RepeatProposal | None:
        try:
            return RepeatProposal(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def get(self, pid: str) -> RepeatProposal | None:
        """A pending proposal that has not expired (an expired one is removed)."""
        if not re.fullmatch(r"rp-[0-9a-f]{6}", pid or ""):
            return None
        path = self.pending_dir / f"{pid}.json"
        p = self._load(path) if path.is_file() else None
        if p is not None and p.expired(self.ttl_s):
            self.drop(pid)
            return None
        return p

    def latest(self, session_id: str | None = None) -> RepeatProposal | None:
        """The newest unexpired proposal (of one chat session, when given)."""
        items = []
        for path in self.pending_dir.glob("rp-*.json"):
            p = self._load(path)
            if p is None:
                continue
            if p.expired(self.ttl_s):
                path.unlink(missing_ok=True)
                continue
            if session_id is None or p.session_id == session_id:
                items.append((p.created_ts, p.created_at, p))
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


def _check_draft(draft: "ScheduleDraft") -> None:
    """Everything ScheduleStore.add would refuse, checked BEFORE the skill is written, so a
    bad schedule never leaves a skill saved on its own."""
    from jarvis.proactive.schedule_parse import KINDS, OUTPUTS, CronError, trigger

    if draft.kind not in KINDS or draft.output not in OUTPUTS or not draft.target:
        raise RepeatError("the schedule draft is incomplete; send /repeat again")
    try:
        trigger(draft.cron, draft.timezone)
    except CronError as e:
        raise RepeatError(str(e)) from None


def save_proposal(p: RepeatProposal, store: RepeatStore, skills_dir: Path, conn: sqlite3.Connection,
                  now: datetime, grace_s: int, audit=None, channel: str = "cli"):
    """Called only after the user said yes to the shown draft. Saves the skill, then the
    schedule (jarvis.proactive.scheduler.ScheduleStore, source "repeat")."""
    from jarvis.proactive.scheduler import ScheduleStore

    draft = replace(p.schedule_draft(), target=skill_name(p.skill_text))
    _check_draft(draft)
    path = save_skill(p.skill_text, skills_dir)
    schedule = ScheduleStore(conn).add(draft, now, grace_s, "repeat")
    store.mark_saved(p, path, schedule.id)
    if audit is not None:
        audit.write("automation_saved", proposal=p.id, source=p.source, skill=str(path), schedule_id=schedule.id,
                    cron=schedule.cron, channel=channel)
    return path, schedule


# ---- the shared flow for chat, Telegram and the CLI ----

def known_tool_tiers(rt: Any, tools: list | None = None) -> dict[str, str]:
    """Tool name -> tier from Jarvis's own registries (chat tools plus browser and Coder tools),
    so a drafted skill shows real tiers, never a model's guess."""
    from jarvis.browser import BrowserSession, browser_tools
    from jarvis.tools.code import CodeTools, coder_tools

    tools = list(tools) if tools is not None else _chat_tools(rt)
    try:
        scratch = rt.paths.data / "repeat"
        tools += browser_tools(BrowserSession(rt.paths.home, scratch, [], config={}), None)
        tools += coder_tools(CodeTools(scratch, {}))
    except Exception:  # tiers of the extra tools are optional context for the draft
        pass
    tiers: dict[str, str] = {}
    for t in tools:
        tiers.setdefault(t.spec.name, t.tier)  # the caller's registry (with its overrides) wins
    return tiers


def _chat_tools(rt: Any) -> list:
    """The chat registry's tools with the private registry's overrides, without a chat session."""
    from jarvis.tools.catalog import ToolDeps, apply_registry, build_registry, registry_path
    from jarvis.tools.registry import ToolRegistry
    from jarvis.tools.system import SystemTools
    from jarvis.tools.web import WebClient

    reg = ToolRegistry(rt.store, rt.audit)
    build_registry(reg, ToolDeps(
        home=rt.paths.home, store=rt.store, audit=rt.audit, memory=rt.memory, skills=rt.skills,
        session_id=lambda: "repeat", max_privacy="P1", tools_config=rt.config.tools, web=WebClient(),
        quarantine=None, tavily_key=lambda: None, system=SystemTools()))
    apply_registry(reg, registry_path(rt.paths.home), rt.audit)
    return reg.all()


def propose(rt: Any, proactive: Any, when: str, *, task_id: str | None = None, session_id: str | None = None,
            tools: list | None = None, owner_session: str | None = None, channel: str = "cli") -> RepeatProposal:
    """Build (not save) a skill + schedule proposal from a completed task (task_id) or the last
    chat action of a session (session_id), and keep it as pending for a yes. owner_session:
    the chat whose "/repeat yes" may confirm it (default: session_id). Raises RepeatError with
    a message for the user. `proactive` is the shared jarvis.proactive.service.Proactive."""
    from jarvis.control.stop import StopSwitch

    if StopSwitch(rt.paths.data).engaged():
        raise RepeatError("Emergency stop is on; nothing is drafted until it is released.")
    tasks = TaskStore(rt.store, rt.paths.data / "tasks")
    if task_id:
        task = tasks.get(task_id)
        if not task:
            raise RepeatError(f"No task {task_id}.")
        if task.state != "COMPLETED":
            raise RepeatError(f"Only a task that completed can be made automatic ({task.id} is {task.state}).")
        evidence, goal, source = task_evidence(rt.store.conn, tasks, task), task.goal, f"task {task.id}"
    elif session_id:
        action = chat_evidence(rt.store.conn, session_id)
        evidence, goal, source = action.evidence, action.goal, f"chat {session_id}"
    else:
        raise RepeatError("Nothing to repeat: give a task id, or ask Jarvis to do something first.")
    decision = decide(rt.config, "skill_draft", proactive.provider_override)
    limit = float(proactive.settings.section("schedules").get("repeat_min_interval_minutes", MIN_INTERVAL_MINUTES))
    proposal = build_proposal(
        evidence, goal, source, when, provider=make_provider(decision.provider, rt.config), decision=decision,
        tool_tiers=known_tool_tiers(rt, tools), parser=proactive.parser(rt, use_model=True),
        defaults={"output": proactive.default_output, "budget": proactive.default_budget},
        session_id=owner_session or session_id or "", now=proactive.now(), min_interval_minutes=limit)
    RepeatStore(rt.paths.data).put(proposal)
    rt.audit.write("automation_proposed", proposal=proposal.id, source=source, cron=proposal.schedule["cron"],
                   skill=proposal.skill, channel=channel)
    return proposal


def confirm(rt: Any, proactive: Any, proposal_id: str, save: bool, channel: str = "cli") -> str:
    """The user's answer to a shown draft. Saves skill + schedule only on an explicit yes for
    an unexpired draft; returns the message for the user."""
    store = RepeatStore(rt.paths.data)
    p = store.get(proposal_id)
    if p is None:
        return "That draft expired or was already answered; nothing was saved. Send /repeat again."
    if not save:
        store.drop(p.id)
        rt.audit.write("automation_dropped", proposal=p.id, source=p.source, channel=channel)
        return "Not saved."
    try:
        path, schedule = save_proposal(p, store, rt.paths.home / "skills", rt.store.conn, proactive.now(),
                                       proactive.grace_s, rt.audit, channel)
    except ValueError as e:  # RepeatError, or ScheduleStore refusing the draft
        return f"Not saved: {e}"
    return (f"Saved skill {p.skill}: {path}\nSaved schedule {schedule.id}: {schedule.line()}\n"
            "It runs while `jarvis daemon` is running; unattended runs do only T0/T1 actions.")
