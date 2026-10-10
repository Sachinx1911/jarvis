"""CLI for Phase 3: tasks, receipts, projects, recordings (teach-by-demonstration) and skills."""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis.core.runtime import Runtime, make_chat, make_task_runner, open_runtime, task_store
from jarvis.projects import ProjectStore
from jarvis.providers import make_provider
from jarvis.tasks.store import PRIORITIES, TransitionError

PROVIDERS = ["claude_code", "anthropic", "fake"]


def register(sub) -> dict[str, Callable]:
    task = sub.add_parser("task", help="add, run, show, cancel or resume tasks")
    task.add_argument("action", choices=["add", "run", "show", "cancel", "resume", "repeat"])
    task.add_argument("text", nargs="*", help="goal text, or a task id (repeat: <task-id> \"<when>\")")
    task.add_argument("--yes", action="store_true", help="repeat: save without asking")
    task.add_argument("--project")
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
                deadline: str | None = None, budget_usd: float | None = None) -> str:
    if project and not ProjectStore(rt.paths.home).exists(project):
        ProjectStore(rt.paths.home).create(project)
    budget = {"max_notional_usd": budget_usd} if budget_usd else None
    return task_store(rt).create(goal, project=project, priority=priority, deadline=deadline, budget=budget).id


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
            tid = create_task(rt, " ".join(args.text), args.project, PRIORITIES[args.priority], args.deadline,
                              args.budget_usd)
            print(f"Added {tid} to the backlog.", file=out)
            return 0
        if action == "run":
            text = " ".join(args.text)
            tid = text if ts.get(text) else create_task(rt, text, args.project, PRIORITIES[args.priority],
                                                        args.deadline, args.budget_usd)
            return run_task(rt, tid, out, approver_factory(), args.workers, args.provider)
        if action == "resume":
            pending = ts.resumable()
            for t in pending:
                run_task(rt, t.id, out, approver_factory(), args.workers, args.provider)
            if not pending:
                print("Nothing to resume.", file=out)
            return 0
        task = ts.get(args.text[0]) if args.text else None
        if not task:
            print("Give a task id (see: jarvis tasks).", file=out)
            return 1
        if action == "repeat":
            return cmd_repeat(rt, task.id, " ".join(args.text[1:]), out, inp, args.provider, args.yes)
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


# ---- "do this every time": /repeat and jarvis task repeat (jarvis/tasks/repeat.py) ----

def known_tool_tiers(rt: Runtime, tools: list | None = None) -> dict[str, str]:
    """Tool name -> tier from Jarvis's own registries (chat tools plus browser and Coder tools),
    so a drafted skill shows real tiers, never a model's guess."""
    from jarvis.browser import BrowserSession, browser_tools
    from jarvis.tools.code import CodeTools, coder_tools

    tools = list(tools) if tools is not None else make_chat(rt, "fake").tools.all()
    try:
        scratch = rt.paths.data / "repeat"
        tools += browser_tools(BrowserSession(rt.paths.home, scratch, [], config={}), None)
        tools += coder_tools(CodeTools(scratch, {}))
    except Exception:  # tiers of the extra tools are optional context for the draft
        pass
    return {t.spec.name: t.tier for t in tools}


def _proactive(provider: str | None):
    from jarvis.proactive.service import Proactive

    return Proactive(provider_override=provider)


def propose_repeat(rt: Runtime, when: str, *, task_id: str | None = None, session_id: str | None = None,
                   provider: str | None = None, tools: list | None = None):
    """Build (not save) a skill + schedule proposal from a completed task or the last chat
    action, and keep it as pending. Raises RepeatError with a message for the user."""
    from jarvis.routing.policy import decide
    from jarvis.tasks.repeat import RepeatError, RepeatStore, build_proposal, chat_evidence, task_evidence

    ts = task_store(rt)
    if task_id:
        task = ts.get(task_id)
        if not task:
            raise RepeatError(f"No task {task_id}.")
        if task.state != "COMPLETED":
            raise RepeatError(f"Only a task that completed can be made automatic ({task.id} is {task.state}).")
        evidence, goal, source = task_evidence(rt.store.conn, ts, task), task.goal, f"task {task.id}"
    elif session_id:
        action = chat_evidence(rt.store.conn, session_id)
        evidence, goal, source = action.evidence, action.goal, f"chat {session_id}"
    else:
        raise RepeatError("Nothing to repeat.")
    p = _proactive(provider)
    d = decide(rt.config, "skill_draft", provider)
    proposal = build_proposal(
        evidence, goal, source, when, provider=make_provider(d.provider, rt.config), decision=d,
        tool_tiers=known_tool_tiers(rt, tools), parser=p.parser(rt, use_model=True),
        defaults={"output": p.default_output, "budget": p.default_budget}, session_id=session_id or "")
    RepeatStore(rt.paths.data).put(proposal)
    rt.audit.write("automation_proposed", proposal=proposal.id, source=source, cron=proposal.schedule["cron"])
    return proposal, p


def _save(rt: Runtime, proposal, p, out: TextIO) -> int:
    from jarvis.tasks.repeat import RepeatStore, save_proposal

    try:
        path, schedule = save_proposal(proposal, RepeatStore(rt.paths.data), rt.paths.home / "skills",
                                       rt.store.conn, p.now(), p.grace_s, rt.audit)
    except ValueError as e:
        print(f"Not saved: {e}", file=out)
        return 1
    print(f"Saved skill {proposal.skill}: {path}\nSaved schedule {schedule.id}: {schedule.line()}\n"
          "It runs while `jarvis daemon` is running.", file=out)
    return 0


def cmd_repeat(rt: Runtime, task_id: str, when: str, out: TextIO, inp: TextIO, provider: str | None,
               yes: bool = False) -> int:
    from jarvis.tasks.repeat import RepeatError, RepeatStore

    try:
        proposal, p = propose_repeat(rt, when, task_id=task_id, provider=provider)
    except RepeatError as e:
        print(str(e), file=out)
        return 1
    print(proposal.show(p.now(), rt.paths.home / "skills"), file=out)
    if not yes:
        out.write("Save this skill and schedule? [y/N] ")
        out.flush()
        if inp.readline().strip().lower() not in ("y", "yes", "ho", "हो"):
            RepeatStore(rt.paths.data).drop(proposal.id)
            print("Not saved.", file=out)
            return 0
    return _save(rt, proposal, p, out)


def chat_repeat(session, rt: Runtime, rest: str, out: TextIO) -> None:
    """/repeat <when> shows a draft; /repeat yes saves it; /repeat no drops it."""
    from jarvis.tasks.repeat import EXAMPLE_WHEN, RepeatError, RepeatStore

    store = RepeatStore(rt.paths.data)
    word = rest.strip().lower()
    if word in ("yes", "y", "save", "ho", "हो", "no", "n", "cancel", "nako", "नको"):
        pending = store.latest(session.session_id)
        if pending is None:
            print(f"Nothing is waiting. Use /repeat {EXAMPLE_WHEN} first.", file=out)
        elif word in ("no", "n", "cancel", "nako", "नको"):
            store.drop(pending.id)
            print("Dropped; nothing was saved.", file=out)
        else:
            _save(rt, pending, _proactive(_chat_provider(session)), out)
        return
    if not word:
        print(f"Usage: /repeat <when>, e.g. /repeat {EXAMPLE_WHEN}. Then /repeat yes to save or /repeat no.",
              file=out)
        return
    task_id = _recent_task(session, rt)
    try:
        proposal, p = propose_repeat(rt, rest, task_id=task_id, session_id=None if task_id else session.session_id,
                                     provider=_chat_provider(session), tools=session.tools.all())
    except RepeatError as e:
        print(str(e), file=out)
        return
    if task_id:  # /repeat yes in this chat finds it
        proposal.session_id = session.session_id
        store.put(proposal)
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


def chat_command(session, rt: Runtime, cmd: str, rest: str, out: TextIO) -> bool:
    """Chat commands: /task, /record, /note, /project. Returns False if not one of them."""
    if cmd == "/project":
        if not rest:
            print(f"Active project: {session.context.project or 'none'}. Projects: {', '.join(ProjectStore(rt.paths.home).list()) or 'none'}", file=out)
        elif rest == "off":
            session.context.project = None
            print("No active project.", file=out)
        elif ProjectStore(rt.paths.home).exists(rest):
            session.context.project = rest
            print(f"Active project: {rest}. Its memories and documents come first.", file=out)
        else:
            print(f"No project {rest} (create it: jarvis project new {rest}).", file=out)
        return True
    if cmd == "/task":
        if not rest:
            print("Usage: /task <goal>", file=out)
        else:
            tid = create_task(rt, rest, session.context.project)
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
