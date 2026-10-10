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
    task.add_argument("action", choices=["add", "run", "show", "cancel", "resume"])
    task.add_argument("text", nargs="*", help="goal text, or a task id")
    task.add_argument("--project")
    task.add_argument("--priority", choices=["high", "normal", "low"], default="normal")
    task.add_argument("--deadline")
    task.add_argument("--workers", help="worker model profile (config/tasks.yaml), e.g. opus or sonnet")
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
                deadline: str | None = None) -> str:
    if project and not ProjectStore(rt.paths.home).exists(project):
        ProjectStore(rt.paths.home).create(project)
    return task_store(rt).create(goal, project=project, priority=priority, deadline=deadline).id


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
            tid = create_task(rt, " ".join(args.text), args.project, PRIORITIES[args.priority], args.deadline)
            print(f"Added {tid} to the backlog.", file=out)
            return 0
        if action == "run":
            text = " ".join(args.text)
            tid = text if ts.get(text) else create_task(rt, text, args.project, PRIORITIES[args.priority], args.deadline)
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


def chat_command(session, rt: Runtime, cmd: str, rest: str, out: TextIO) -> bool:
    """Chat commands: /task, /record, /note. Returns False if not one of them."""
    if cmd == "/task":
        if not rest:
            print("Usage: /task <goal>", file=out)
        else:
            run_task(rt, create_task(rt, rest), out, session.approver_for_tasks)
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
