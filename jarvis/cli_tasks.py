"""CLI for Phase 3: tasks, receipts, projects, recordings (teach-by-demonstration) and skills."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, TextIO

from jarvis.core.runtime import Runtime, make_chat, make_task_runner, open_runtime, task_store
from jarvis.projects import ProjectStore
from jarvis.providers import make_provider
from jarvis.tasks.store import PRIORITIES, TransitionError
from jarvis.workspaces.model import PERSONAL, WorkspaceError
from jarvis.workspaces.routing import Routing, route
from jarvis.workspaces.session import enter_workspace
from jarvis.workspaces.store import WorkspaceStore

PROVIDERS = ["claude_code", "anthropic", "fake"]


def register(sub) -> dict[str, Callable]:
    task = sub.add_parser("task", help="add, run, show, cancel or resume tasks")
    task.add_argument("action", choices=["add", "run", "show", "cancel", "resume", "repeat", "draft"])
    task.add_argument("text", nargs="*", help="goal text, or a task id (repeat: <task-id> \"<when>\")")
    task.add_argument("--project")
    task.add_argument("--workspace", help="the office (workspace slug); without it the goal is routed by duties")
    task.add_argument("--priority", choices=["high", "normal", "low"], default="normal")
    task.add_argument("--deadline")
    task.add_argument("--workers", help="worker model profile (config/tasks.yaml), e.g. opus or sonnet")
    task.add_argument("--budget-usd", type=float, help="notional cost limit for this task (default in config/tasks.yaml)")
    task.add_argument("--provider", choices=PROVIDERS, default=None)
    tasks = sub.add_parser("tasks", help="list tasks")
    tasks.add_argument("--all", action="store_true", help="include finished tasks")
    rc = sub.add_parser("receipt", help="show a task receipt")
    rc.add_argument("id")

    proj = sub.add_parser("project", help="create or list projects")
    proj.add_argument("action", choices=["new", "list"])
    proj.add_argument("name", nargs="?", default="")
    proj.add_argument("goal", nargs="*")

    rec = sub.add_parser("record", help="teach by demonstration: start, note, stop, draft, approve")
    rec.add_argument("action", choices=["start", "note", "stop", "draft", "approve"])
    rec.add_argument("text", nargs="*")
    rec.add_argument("--provider", choices=PROVIDERS, default=None)

    sk = sub.add_parser("skill", help="list skills or run one")
    sk.add_argument("action", choices=["list", "run"])
    sk.add_argument("text", nargs="*", help="skill name, then inputs")
    sk.add_argument("--provider", choices=PROVIDERS, default=None)
    return {"task": cmd_task, "tasks": cmd_task, "receipt": cmd_task, "project": cmd_project,
            "record": cmd_record, "skill": cmd_skill}


def create_task(rt: Runtime, goal: str, project: str | None = None, priority: int = 2,
                deadline: str | None = None, budget_usd: float | None = None, workspace: str | None = None) -> str:
    """A task belongs to one workspace (law 4): the one given, else its project's owner, else personal.
    An archived or unknown workspace raises WorkspaceError (a ValueError)."""
    if project and not ProjectStore(rt.paths.home).exists(project):
        ProjectStore(rt.paths.home).create(project)
    budget = {"max_notional_usd": budget_usd} if budget_usd else None
    ws = WorkspaceStore(rt.paths.home)
    workspace = ws.active(workspace).slug if workspace else ws.workspace_of_project(project)
    return task_store(rt).create(goal, project=project, priority=priority, deadline=deadline, budget=budget,
                                 workspace=workspace).id


def route_goal(rt: Runtime, goal: str) -> Routing:
    """Dharma routing (PLAN.md 27.5 step 2): the office a goal belongs to, by the workspaces' duties."""
    return route(goal, WorkspaceStore(rt.paths.home).list())


def record_routing(rt: Runtime, goal: str, slug: str, routing: Routing, source: str, channel: str,
                   task_id: str | None = None) -> None:
    """Chitragupta (law 3): every routing decision, automatic or Sachin's own choice, is in the audit log."""
    rt.audit.write("task_routed", task_id=task_id, workspace=slug, source=source, channel=channel,
                   confidence=routing.confidence, reasons=routing.reasons, goal=goal[:200])


def choose_workspace(rt: Runtime, goal: str, out: TextIO, inp: TextIO | None, channel: str = "chat") -> str | None:
    """Route a goal that has no office yet. Sure: say so in one line and use it. Unsure: ask with the
    candidates as a numbered prompt (an empty or unknown answer starts nothing). Returns the slug or None."""
    routing = route_goal(rt, goal)
    if routing.sure:
        if len(routing.candidates) > 1:  # silent when personal is the only office
            print(routing.line(), file=out)
        record_routing(rt, goal, routing.slug or PERSONAL, routing, "auto", channel)
        return routing.slug
    print(routing.line(), file=out)
    out.write("Office number (or Enter to cancel): ")
    out.flush()
    answer = ((inp or sys.stdin).readline() or "").strip()
    pick = None
    if answer.isdigit() and 1 <= int(answer) <= len(routing.candidates):
        pick = routing.candidates[int(answer) - 1]
    else:
        pick = next((c for c in routing.candidates if answer and answer.lower() in (c.slug, c.name.lower())), None)
    if pick is None:
        print("Not started. Say /workspace <slug> first, or /task again with a clearer goal.", file=out)
        record_routing(rt, goal, "", routing, "cancelled", channel)
        return None
    record_routing(rt, goal, pick.slug, routing, "user", channel)
    return pick.slug


_CANCELLED = object()


def _cli_workspace(rt: Runtime, args: argparse.Namespace, goal: str, out: TextIO, inp: TextIO | None):
    """`jarvis task add|run`: --workspace or --project decide; otherwise route by duties and ask when unsure."""
    if getattr(args, "workspace", None):
        return args.workspace
    if args.project:
        return None  # create_task takes the project's owner (law 4)
    chosen = choose_workspace(rt, goal, out, inp, channel="cli")
    return _CANCELLED if chosen is None else chosen


def run_task(rt: Runtime, task_id: str, out: TextIO, approver, workers: str | None = None,
             provider: str | None = None) -> int:
    runner = make_task_runner(rt, provider, approver, workers, progress=lambda m: print(f"  ... {m}", file=out))
    print(f"Task {task_id} started.", file=out)
    task = runner.run(task_id)
    receipt = rt.paths.data / "tasks" / task_id / "receipt.md"
    print(f"Task {task_id}: {task.state}.", file=out)
    if receipt.exists():
        print(receipt.read_text(encoding="utf-8"), file=out)
    return 0 if task.state == "COMPLETED" else 1


def cmd_task(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    rt = open_runtime()
    try:
        ts = task_store(rt)
        if args.command == "tasks":
            rows = ts.list(include_final=args.all)
            for t in rows:
                print(f"{t.id}  {t.state:<16} p{t.priority}  {t.title[:50]:<50}  {t.current_step or ''}", file=out)
            if not rows:
                print("No tasks.", file=out)
            return 0
        if args.command == "receipt":
            path = rt.paths.data / "tasks" / args.id / "receipt.md"
            print(path.read_text(encoding="utf-8") if path.exists() else "No receipt yet.", file=out)
            return 0
        action = args.action
        if action == "add":
            goal = " ".join(args.text)
            workspace = _cli_workspace(rt, args, goal, out, inp)
            if workspace is _CANCELLED:
                return 1
            tid = create_task(rt, goal, args.project, PRIORITIES[args.priority], args.deadline, args.budget_usd,
                              workspace=workspace)
            print(f"Added {tid} to the backlog.", file=out)
            return 0
        if action == "run":
            text = " ".join(args.text)
            if ts.get(text):
                tid = text
            else:
                workspace = _cli_workspace(rt, args, text, out, inp)
                if workspace is _CANCELLED:
                    return 1
                tid = create_task(rt, text, args.project, PRIORITIES[args.priority], args.deadline, args.budget_usd,
                                  workspace=workspace)
            return run_task(rt, tid, out, approver_factory(), args.workers, args.provider)
        if action == "resume":
            pending = ts.resumable()
            for t in pending:
                run_task(rt, t.id, out, approver_factory(), args.workers, args.provider)
            if not pending:
                print("Nothing to resume.", file=out)
            return 0
        if action == "draft":  # a pending /repeat draft, shown in full on this computer only
            from jarvis.tasks.repeat import RepeatStore

            p = RepeatStore(rt.paths.data).get(args.text[0]) if args.text else None
            if p is None:
                print("No such draft waiting (drafts expire after an hour). Give an id like rp-1a2b3c.", file=out)
                return 1
            print(p.show(None, rt.paths.home / "skills"), file=out)
            return 0
        task = ts.get(args.text[0]) if args.text else None
        if not task:
            print("Give a task id (see: jarvis tasks).", file=out)
            return 1
        if action == "repeat":
            return cmd_repeat(rt, task.id, " ".join(args.text[1:]), out, inp, args.provider)
        if action == "show":
            print(f"{task.id} [{task.state}] {task.title}\nGoal: {task.goal}\nProject: {task.project or '-'}\n"
                  f"Step: {task.current_step or '-'}\nError: {task.last_error or '-'}\nUsage: {ts.usage(task.id)}", file=out)
            for e in ts.events(task.id):
                print(f"  {e['ts']} {e['kind']}: {str(e['detail'])[:150]}", file=out)
        elif action == "cancel":
            ts.set_state(task.id, "CANCELLED", "cancelled by user")
            print(f"Cancelled {task.id}.", file=out)
        return 0
    except TransitionError as e:
        print(str(e), file=out)
        return 1
    finally:
        rt.close()


def cmd_project(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    rt = open_runtime()
    try:
        ps = ProjectStore(rt.paths.home)
        if args.action == "new":
            print(f"Project ready: {ps.create(args.name, ' '.join(args.goal))}", file=out)
        else:
            for name in ps.list():
                print(name, file=out)
        return 0
    finally:
        rt.close()


def recorder(rt: Runtime):
    from jarvis.skills.recorder import Recorder
    from jarvis.tools.catalog import file_roots

    return Recorder(rt.paths.home, rt.store, file_roots(rt.paths.home, rt.config.tools))


def cmd_record(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.routing.policy import decide

    rt = open_runtime()
    try:
        rec = recorder(rt)
        try:
            if args.action == "start":
                r = rec.start(" ".join(args.text) or "demo")
                print(f"Recording {r.id} started. Now do the task in `jarvis chat`.\n{rec.terminal_hint(r)}", file=out)
            elif args.action == "note":
                rec.note(" ".join(args.text))
                print("Noted.", file=out)
            elif args.action == "stop":
                r, evidence = rec.stop()
                print(evidence, file=out)
                print(f"Recording {r.id} stopped. Next: jarvis record draft {r.id}", file=out)
            elif args.action == "draft":
                rid = args.text[0]
                d = decide(rt.config, "skill_draft", args.provider)
                tiers = {t.spec.name: t.tier for t in make_chat(rt, "fake").tools.all()}
                path = rec.draft(rid, make_provider(d.provider, rt.config), d, tiers)
                print(path.read_text(encoding="utf-8"), file=out)
                print(f"Draft saved: {path}\nEdit it if needed, then approve: jarvis record approve {rid}", file=out)
            elif args.action == "approve":
                path = rec.approve(args.text[0], rt.paths.home / "skills")
                rt.audit.write("skill_approved", recording=args.text[0], path=str(path))
                print(f"Skill saved: {path}", file=out)
            return 0
        except (RuntimeError, FileNotFoundError, ValueError, IndexError) as e:
            print(f"Error: {e}", file=out)
            return 1
    finally:
        rt.close()


def cmd_skill(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.skills.loader import SkillLibrary

    rt = open_runtime()
    try:
        lib = SkillLibrary(rt.paths.home / "skills")
        if args.action == "list":
            for s in lib.index():
                print(f"{s.name}: {s.description}", file=out)
            return 0
        name = args.text[0] if args.text else ""
        if not lib.load(name):
            print(f"No skill named {name}.", file=out)
            return 1
        inputs = " ".join(args.text[1:])
        session = make_chat(rt, args.provider, approver_factory())
        msg = f"Load the skill {name} with load_skill and carry it out" + (f" with these inputs: {inputs}" if inputs else "") + "."
        print(f"Jarvis: {session.send(msg)}", file=out)
        return 0
    finally:
        rt.close()


# ---- repeat-this: /repeat and jarvis task repeat (jarvis/tasks/repeat.py) ----

def _proactive(provider: str | None):
    from jarvis.proactive.service import Proactive

    return Proactive(provider_override=provider)


def cmd_repeat(rt: Runtime, task_id: str, when: str, out: TextIO, inp: TextIO, provider: str | None) -> int:
    """Shows the skill + schedule draft, then asks. Only an explicit yes to that shown draft
    saves anything; there is deliberately no flag that saves without asking."""
    from jarvis.tasks.repeat import YES_WORDS, RepeatError, confirm, propose

    p = _proactive(provider)
    try:
        proposal = propose(rt, p, when, task_id=task_id, channel="cli")
    except RepeatError as e:
        print(str(e), file=out)
        return 1
    print(proposal.show(p.now(), rt.paths.home / "skills"), file=out)
    out.write("Save this skill and schedule? [y/N] ")
    out.flush()
    yes = inp.readline().strip().lower() in YES_WORDS
    message = confirm(rt, p, proposal.id, yes, channel="cli")
    print(message, file=out)
    return 0 if not yes or message.startswith("Saved") else 1


def chat_repeat(session, rt: Runtime, rest: str, out: TextIO) -> None:
    """/repeat [<task id>] <when> shows a draft; /repeat yes saves it; /repeat no drops it."""
    from jarvis.tasks.repeat import (EXAMPLE_WHEN, NO_WORDS, YES_WORDS, RepeatError, RepeatStore, confirm, propose,
                                     split_task_id)

    word = rest.strip().lower()
    p = _proactive(_chat_provider(session))
    if word in YES_WORDS | NO_WORDS:
        pending = RepeatStore(rt.paths.data).latest(session.session_id)
        if pending is None:
            print(f"Nothing is waiting (drafts expire after an hour). Use /repeat {EXAMPLE_WHEN} first.", file=out)
            return
        print(confirm(rt, p, pending.id, word in YES_WORDS, channel="chat"), file=out)
        return
    if not word:
        print(f"Usage: /repeat <when>, e.g. /repeat {EXAMPLE_WHEN} (or /repeat <task id> <when>). "
              "Then /repeat yes to save or /repeat no.", file=out)
        return
    task_id, when = split_task_id(rest)
    task_id = task_id or _recent_task(session, rt)
    try:
        proposal = propose(rt, p, when, task_id=task_id, session_id=None if task_id else session.session_id,
                           tools=session.tools.all(), owner_session=session.session_id, channel="chat")
    except RepeatError as e:
        print(str(e), file=out)
        return
    print(proposal.show(p.now(), rt.paths.home / "skills"), file=out)
    print("Save both? Reply /repeat yes to save, or /repeat no.", file=out)


def _chat_provider(session) -> str | None:
    return "fake" if getattr(session.decision, "provider", None) == "fake" else None


def _recent_task(session, rt: Runtime) -> str | None:
    """The task run with /task in this chat, if it is newer than the last chat message."""
    tid = getattr(session, "last_task_id", None)
    task = task_store(rt).get(tid) if tid else None
    if not task:
        return None
    row = rt.store.conn.execute("SELECT MAX(ts) FROM messages WHERE session_id=? AND role='user'",
                                (session.session_id,)).fetchone()
    return task.id if not row or not row[0] or task.updated_at >= row[0] else None


def chat_command(session, rt: Runtime, cmd: str, rest: str, out: TextIO, inp: TextIO | None = None) -> bool:
    """Chat commands: /task, /repeat, /record, /note, /project, /workspace. Returns False if not one of them.
    `inp` answers the routing question of /task (stdin when the caller gives none)."""
    if cmd == "/project":
        if not rest:
            print(f"Active project: {session.context.project or 'none'}. Projects: {', '.join(ProjectStore(rt.paths.home).list()) or 'none'}", file=out)
        elif rest == "off":
            session.context.project = None
            print("No active project.", file=out)
        elif ProjectStore(rt.paths.home).exists(rest):
            ws = WorkspaceStore(rt.paths.home)
            try:
                w = enter_workspace(session, ws, ws.workspace_of_project(rest))  # the project's owner (law 4)
            except WorkspaceError as e:
                print(str(e), file=out)
                return True
            session.context.project = rest
            where = "" if w.personal else f" Workspace: {w.name}."
            print(f"Active project: {rest}. Its memories and documents come first.{where}", file=out)
        else:
            print(f"No project {rest} (create it: jarvis project new {rest}).", file=out)
        return True
    if cmd == "/workspace":
        ws = WorkspaceStore(rt.paths.home)
        if not rest:
            names = ", ".join(w.slug for w in ws.list()) or PERSONAL
            print(f"Active workspace: {session.context.workspace}. Workspaces: {names}", file=out)
        else:
            try:
                w = enter_workspace(session, ws, PERSONAL if rest == "off" else rest)
            except WorkspaceError as e:
                print(str(e), file=out)
                return True
            session.workspace_pinned = rest != "off"  # Sachin chose: /task never re-routes (27.5)
            shared = "" if w.personal else (" Personal memories are in view too." if w.share_personal else " Personal memories stay out of view.")
            print(f"Workspace: {w.name} ({w.slug}).{shared}", file=out)
        return True
    if cmd == "/task":
        if not rest:
            print("Usage: /task <goal>", file=out)
            return True
        # Dharma routing (PLAN.md 27.5): an office Sachin set (/workspace) or a project's owner is never
        # re-routed; otherwise the goal's words decide, and Jarvis asks when unsure.
        if session.context.project or getattr(session, "workspace_pinned", False):
            workspace: str | None = session.context.workspace
        else:
            workspace = choose_workspace(rt, rest, out, inp, channel="chat")
            if workspace is None:
                return True
        tid = create_task(rt, rest, session.context.project, workspace=workspace)
        session.last_task_id = tid  # /repeat after /task automates the task
        run_task(rt, tid, out, session.approver_for_tasks)
        return True
    if cmd == "/repeat":
        chat_repeat(session, rt, rest, out)
        return True
    if cmd in ("/record", "/note"):
        rec = recorder(rt)
        try:
            if cmd == "/note":
                rec.note(rest)
                print("Noted.", file=out)
            elif rest.startswith("start"):
                r = rec.start(rest[5:].strip() or "demo")
                print(f"Recording {r.id} started. {rec.terminal_hint(r)}", file=out)
            elif rest.startswith("stop"):
                r, _ = rec.stop()
                print(f"Recording {r.id} stopped. Draft a skill with: jarvis record draft {r.id}", file=out)
            else:
                print("Usage: /record start <name> | /record stop | /note <why>", file=out)
        except RuntimeError as e:
            print(str(e), file=out)
        return True
    return False
