"""Command line: jarvis init | chat | memory | sessions | interview | eval | connectors | stop | resume | secret | health."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import TextIO

from jarvis.config import load_config
from jarvis.control.approvals import ApprovalRequest
from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import Runtime, make_chat, make_extractor, open_runtime
from jarvis.memory.store import MemoryRejected
from jarvis.paths import PROMPTS_DIR, default_paths
from jarvis.providers import make_provider
from jarvis.providers.base import ProviderError
from jarvis.routing.policy import RoutingError
from jarvis.secrets import KNOWN_SECRETS, get_secret, set_secret
from jarvis.tools.catalog import file_roots, registry_path

EXIT_WORDS = {"/exit", "/quit", "exit", "quit"}
PROVIDERS = ["claude_code", "anthropic", "fake"]

CHAT_HELP = """Commands:
  /remember <text>          save a memory now
  /remember-private <text>  save a sensitive memory (kept local, never sent to the cloud)
  /memory <words>           search memories
  /forget <id>              archive a memory
  /why                      what Jarvis had in mind for its last answer (memories, past chats)
  /task <goal>              run a task now (plan, team, check, receipt)
  /repeat [<task id>] <when> turn the last action (or a task) into a skill + schedule; /repeat yes|no
  /record start <name>      record a demonstration (/record stop, /note <why>)
  /project <name>|off       set the active project (its memories and documents come first)
  /workspace <slug>|off     work in an office (company); its memories are in view, others' are not
  /ask <slug> <goal>        ask another office for work (Narada); only its result comes back
  /requests [all]           requests from or to this office, with their state and result
  /exit                     end the chat (Jarvis then saves what it learned)"""


def cmd_init(args: argparse.Namespace, out: TextIO) -> int:
    rt = open_runtime()
    rt.audit.write("init", home=str(rt.paths.home))
    rt.close()
    print(f"Jarvis home ready: {rt.paths.home}", file=out)
    return 0


def _print_results(results: list[tuple[str, str]], out: TextIO) -> None:
    saved = [r for r in results if r[0] in ("ADD", "UPDATE", "SUPERSEDE")]
    if saved:
        print("Learned: " + ", ".join(f"{a.lower()} {mid}" for a, mid in saved), file=out)


def _slash(session: ChatSession, rt: Runtime, text: str, out: TextIO, inp: TextIO | None = None) -> bool:
    """Handle a chat command. Returns False if text is not a command."""
    cmd, _, rest = text.partition(" ")
    rest = rest.strip()
    if cmd in ("/remember", "/remember-private"):
        if session.extractor is None:
            print("Memory is not available.", file=out)
            return True
        try:
            mem = session.extractor.remember(rest, private=cmd == "/remember-private", workspace=session.workspace,
                                             share_personal=session.context.share_personal)
            print(f"Remembered as {mem.id}: {mem.summary_en or mem.name}", file=out)
        except (MemoryRejected, ValueError) as e:
            print(f"Not saved: {e}", file=out)
        return True
    if cmd == "/memory":
        hits = rt.memory.search(rest)
        for h in hits:
            print(f"  {h.memory.id} [{h.memory.type}] {h.memory.summary_en or h.memory.name}", file=out)
        if not hits:
            print("  No matching memories.", file=out)
        return True
    if cmd == "/forget":
        try:
            rt.memory.archive(rest)
            print(f"Archived {rest}.", file=out)
        except KeyError:
            print(f"No memory {rest}.", file=out)
        return True
    if cmd == "/help":
        print(CHAT_HELP, file=out)
        return True
    if cmd == "/why":
        print(why_text(rt, getattr(session, "last_turn_id", None)), file=out)
        return True
    from jarvis import cli_tasks
    return cli_tasks.chat_command(session, rt, cmd, rest, out, inp)


def why_text(rt: Runtime, turn_id: int | None) -> str:
    """The last answer's context: memories and past-chat lines it was given (as the dashboard's
    "why" panel). Sensitive memories show only their name; their text stays hidden."""
    from jarvis.web.trust import turn_view

    view = turn_view(rt, turn_id) if turn_id else None
    if not view:
        return "Nothing to explain yet: ask something first."
    lines = ["Context Jarvis had for its last answer:"]
    for m in view["memories"]:
        detail = "" if m.get("masked") or not m.get("summary_en") else f": {m['summary_en']}"
        lines.append(f"- memory {m['id']} {m['name']} ({m.get('type') or '-'}, {m.get('status') or '-'}){detail}")
    for x in view["excerpts"]:
        lines.append(f"- past chat {x.get('ts', '')} {x.get('role', '')}: {str(x.get('text', ''))[:160]}")
    if len(lines) == 1:
        lines.append("- no memories or past chats: the answer came from the conversation itself.")
    if view.get("withheld"):
        lines.append(f"{view['withheld']} private item(s) were kept from the cloud model.")
    return "\n".join(lines)


def terminal_approver(out: TextIO, inp: TextIO):
    """Ask in the terminal, showing the exact arguments. Anything but y/yes/ho means no."""
    def ask(req: ApprovalRequest) -> bool:
        print("\n" + req.describe(), file=out)
        out.write("Allow? [y/N] ")
        out.flush()
        return inp.readline().strip().lower() in ("y", "yes", "ho", "हो")
    return ask


def cmd_chat(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    rt = open_runtime()
    try:
        try:
            # One-shot messages have nobody to ask, so actions that need approval are denied.
            approver = None if args.message is not None else terminal_approver(out, inp)
            session = make_chat(rt, args.provider, approver)
        except RoutingError as e:
            print(f"Routing error: {e}", file=out)
            return 2

        def turn(text: str) -> bool:
            try:
                print(f"Jarvis: {session.send(text)}", file=out)
                return True
            except ProviderError as e:
                print(f"Error ({e.kind}): {e}", file=out)
            except EmergencyStop as e:
                print(f"Stopped: {e}", file=out)
            return False

        if args.message is not None:
            return 0 if turn(args.message) else 1

        d = session.decision
        print(f"Jarvis ({d.provider}/{d.model}). /help for commands, /exit to quit.", file=out)
        while True:
            out.write("You: ")
            out.flush()
            line = inp.readline()
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                break
            if text.startswith("/") and _slash(session, rt, text, out, inp):
                continue
            turn(text)
        try:
            _print_results(session.end(), out)
        except (ProviderError, EmergencyStop) as e:
            print(f"Could not save memories: {e}", file=out)
        return 0
    finally:
        rt.close()


def cmd_memory(args: argparse.Namespace, out: TextIO) -> int:
    rt = open_runtime()
    try:
        mem = rt.memory
        if args.action == "list":
            for m in mem.list(type=args.type, status=None if args.all else "active"):
                print(f"{m.id} [{m.type}, {m.status}] {m.summary_en or m.name}", file=out)
        elif args.action == "search":
            for h in mem.search(" ".join(args.text)):
                print(f"{h.memory.id} ({h.score:.3f}) [{h.memory.type}] {h.memory.summary_en or h.memory.name}", file=out)
        elif args.action == "show":
            m = mem.get(args.text[0]) if args.text else None
            if not m:
                print("Not found.", file=out)
                return 1
            print(m.to_markdown(), file=out)
        elif args.action == "archive":
            mem.archive(args.text[0])
            print(f"Archived {args.text[0]}.", file=out)
        elif args.action == "export":
            n = mem.export(Path(args.text[0]))
            print(f"Exported {n} memories to {args.text[0]}.", file=out)
        elif args.action == "reindex":
            from jarvis.memory import session_facts
            print(f"Indexed {mem.reindex()} memory files.", file=out)
            session_facts.reindex_all(rt.store.conn)  # facts of chats extracted before this index existed
        elif args.action == "conflicts":
            from jarvis.memory.conflicts import find_conflicts
            found = find_conflicts(mem.list(status="active"))
            if not found:
                print("No possible memory conflicts.", file=out)
            for c in found:
                print(f"Subject {c.subject!r} ({c.type}): {len(c.memories)} active memories disagree", file=out)
                for m in c.memories:
                    print(f"  {m.id} (from {m.valid_from}): {m.summary_en or m.name}: {m.body.strip()[:200]}", file=out)
            if found:
                print("Keep the right one; archive the other with `jarvis memory archive <id>`.", file=out)
        elif args.action == "core":
            from jarvis.memory.core import core_from_settings
            from jarvis.memory.upkeep_settings import load_memory_settings

            core = core_from_settings(rt.paths.home, load_memory_settings())
            if core is None:
                print("Core memory is turned off (config/memory.yaml: core.enabled).", file=out)
                return 0
            for target, st in core.status().items():
                print(f"{st['file']} ({st['used']}/{st['limit']} characters):", file=out)
                for e in st["entries"]:
                    print(f"  - {e}", file=out)
                if not st["entries"]:
                    print("  (empty)", file=out)
        elif args.action == "add":
            saved = make_extractor(rt, args.provider).remember(" ".join(args.text), private=args.private)
            print(f"Remembered as {saved.id}: {saved.summary_en or saved.name}", file=out)
        return 0
    except (KeyError, IndexError):
        print("Give a memory id (see: jarvis memory list).", file=out)
        return 1
    except MemoryRejected as e:
        print(f"Not saved: {e}", file=out)
        return 1
    finally:
        rt.close()


def cmd_sessions(args: argparse.Namespace, out: TextIO) -> int:
    rt = open_runtime()
    try:
        for r in rt.store.search_sessions(" ".join(args.text), limit=10):
            print(f"{r['ts']} {r['session_id']} {r['role']}: {r['text'][:200]}", file=out)
        return 0
    finally:
        rt.close()


def cmd_interview(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    """Profile interview: fixed questions; each answer is saved as a memory in the user's words."""
    questions = [l[2:].strip() for l in (PROMPTS_DIR / "interview.md").read_text(encoding="utf-8").splitlines()
                 if l.startswith("- ")]
    rt = open_runtime()
    try:
        extractor = make_extractor(rt, args.provider)
        print("Answer in English or Marathi. Press Enter to skip a question, type /stop to end.", file=out)
        for q in questions:
            out.write(f"\n{q}\n> ")
            out.flush()
            answer = inp.readline().strip()
            if answer == "/stop":
                break
            if not answer:
                continue
            try:
                m = extractor.remember(f"{q} {answer}" if len(answer) < 40 else answer)
                print(f"  saved {m.id}: {m.summary_en or m.name}", file=out)
            except MemoryRejected as e:
                print(f"  not saved: {e}", file=out)
        return 0
    finally:
        rt.close()


def cmd_eval(args: argparse.Namespace, out: TextIO) -> int:
    if getattr(args, "suite", "migration") == "memory":
        from jarvis.evals.memory_eval import run_cli
        return run_cli(args, out)
    from jarvis.evals.runner import run_suite

    rt = open_runtime()
    try:
        report = run_suite(rt, args.provider, args.category)
        for r in report.results:
            print(f"{'PASS' if r.passed else 'FAIL'} {r.task_id} [{r.category}/{r.language}] {r.detail}", file=out)
        print(f"{report.passed}/{len(report.results)} passed. Saved: {report.path}", file=out)
        return 0
    finally:
        rt.close()


def cmd_connectors(args: argparse.Namespace, out: TextIO) -> int:
    rt = open_runtime()
    try:
        session = make_chat(rt, "fake")  # builds the tool registry without calling any model
        print(f"Registry: {registry_path(rt.paths.home)}", file=out)
        for t in sorted(session.tools.all(), key=lambda t: (t.tier, t.spec.name)):
            print(f"  {t.tier}  {t.spec.name:<15} {'enabled' if t.enabled else 'DISABLED'}", file=out)
        print("Health:", file=out)
        print(f"  tavily key: {'set' if get_secret('tavily_api_key') else 'NOT SET (jarvis secret set tavily_api_key)'}", file=out)
        roots = file_roots(rt.paths.home, rt.config.tools)
        print("  file folders: " + ", ".join(str(r) for r in roots), file=out)
        for name in ("claude_code",):
            h = make_provider(name, rt.config).health()
            print(f"  {name}: {'OK' if h.ok else 'NOT OK'} - {h.detail}", file=out)
        from jarvis.connectors.registry import ConnectorDeps, connector_health
        live = bool(getattr(args, "live", False))
        for cname, ok, detail in connector_health(ConnectorDeps(rt.paths.home, rt.store, rt.audit),
                                                  live=live, notes_live=live):
            print(f"  {cname}: {'OK' if ok else 'NOT OK'} - {detail}", file=out)
        return 0
    finally:
        rt.close()


def cmd_stop(args: argparse.Namespace, out: TextIO) -> int:
    paths = default_paths()
    switch = StopSwitch(paths.data)
    if args.command == "stop":
        switch.engage(" ".join(args.reason))
        AuditLog(paths.audit_log).write("emergency_stop", reason=" ".join(args.reason))
        print("Emergency stop ON. Jarvis will not call any model or tool. Undo: jarvis resume", file=out)
    else:
        switch.release()
        AuditLog(paths.audit_log).write("emergency_stop_released")
        print("Emergency stop OFF.", file=out)
    return 0


def cmd_secret(args: argparse.Namespace, out: TextIO) -> int:
    if args.action == "status":
        for name in KNOWN_SECRETS:
            print(f"{name}: {'set' if get_secret(name) else 'not set'}", file=out)
        return 0
    if args.name not in KNOWN_SECRETS:
        print(f"Unknown secret. Known: {', '.join(KNOWN_SECRETS)}", file=out)
        return 2
    value = getpass.getpass(f"Paste {args.name} (input hidden): ").strip()
    if not value:
        print("Nothing entered; unchanged.", file=out)
        return 1
    set_secret(args.name, value)
    AuditLog(default_paths().audit_log).write("secret_set", name=args.name)
    print(f"{args.name} saved in the OS secret store.", file=out)
    return 0


def cmd_health(args: argparse.Namespace, out: TextIO) -> int:
    config = load_config()
    for name in PROVIDERS:
        h = make_provider(name, config).health()
        print(f"{name}: {'OK' if h.ok else 'NOT OK'} - {h.detail}", file=out)
    if StopSwitch(default_paths().data).engaged():
        print("Emergency stop is ON (jarvis resume to release).", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create folders, database and audit log")

    chat = sub.add_parser("chat", help="chat with Jarvis")
    chat.add_argument("--provider", choices=PROVIDERS, default=None)
    chat.add_argument("-m", "--message", help="send one message and exit")

    mem = sub.add_parser("memory", help="list, search, show, archive, export, reindex or add memories")
    mem.add_argument("action", choices=["list", "search", "show", "archive", "export", "reindex", "add", "conflicts",
                                        "core"])
    mem.add_argument("text", nargs="*")
    mem.add_argument("--type", choices=["fact", "preference", "procedure", "constraint", "episode"])
    mem.add_argument("--all", action="store_true", help="include superseded and archived")
    mem.add_argument("--private", action="store_true", help="add: keep local, never sent to the cloud")
    mem.add_argument("--provider", choices=PROVIDERS, default=None)

    ses = sub.add_parser("sessions", help="search past conversations")
    ses.add_argument("action", choices=["search"])
    ses.add_argument("text", nargs="+")

    iv = sub.add_parser("interview", help="profile interview; answers become memories")
    iv.add_argument("--provider", choices=PROVIDERS, default=None)

    ev = sub.add_parser("eval", help="run an evaluation suite (migration or memory)")
    ev.add_argument("--provider", choices=PROVIDERS, default=None)
    ev.add_argument("--category", default=None)
    ev.add_argument("--suite", choices=["migration", "memory"], default="migration")
    ev.add_argument("--live", action="store_true", help="memory suite: also measure answers with the real model")

    con = sub.add_parser("connectors", help="tools, risk tiers and health checks")
    con.add_argument("action", choices=["status"])
    con.add_argument("--live", action="store_true",
                     help="also run the live checks: one small Google call and one Apple Event to Notes "
                          "(Notes may show the macOS permission prompt; no note is read)")

    stop = sub.add_parser("stop", help="emergency stop: block all model and tool calls")
    stop.add_argument("reason", nargs="*")
    sub.add_parser("resume", help="release the emergency stop")

    sec = sub.add_parser("secret", help="manage secrets in the OS secret store")
    sec.add_argument("action", choices=["set", "status"])
    sec.add_argument("name", nargs="?", default="anthropic_api_key")
    sub.add_parser("health", help="check providers")
    return p


def build_parser_with_extensions():
    """Core commands plus the command groups from other modules (each has register())."""
    from jarvis import cli_app, cli_browser, cli_connectors, cli_memory, cli_proactive, cli_tasks, cli_voice, cli_web
    from jarvis import cli_approvals, cli_backup, cli_india, cli_workspaces

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    extra: dict = {}
    for module in (cli_tasks, cli_browser, cli_web, cli_memory, cli_app, cli_approvals, cli_india, cli_backup,
                   cli_workspaces):
        extra.update(module.register(sub))
    cli_voice.register(sub)
    cli_connectors.register(sub)
    cli_proactive.register(sub)
    for name in cli_proactive.COMMANDS:
        extra[name] = lambda args, out, inp, approvers: cli_proactive.handle(args, out, inp)
    for name in cli_connectors.COMMANDS:
        extra[name] = lambda args, out, inp, approvers: cli_connectors.handlers(args, out)[args.command]()
    for name, handler in cli_voice.HANDLERS.items():
        extra[name] = lambda args, out, inp, approvers, h=handler: h(args, out, inp)
    return parser, extra


def main(argv: list[str] | None = None, out: TextIO | None = None, inp: TextIO | None = None) -> int:
    if out is None:
        for stream in (sys.stdout, sys.stdin):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")  # Marathi on Windows consoles
    out = out or sys.stdout
    inp = inp or sys.stdin
    parser, extra = build_parser_with_extensions()
    args = parser.parse_args(argv)
    if args.command in extra:
        return extra[args.command](args, out, inp, lambda: terminal_approver(out, inp))
    handlers = {
        "init": lambda: cmd_init(args, out),
        "chat": lambda: cmd_chat(args, out, inp),
        "memory": lambda: cmd_memory(args, out),
        "sessions": lambda: cmd_sessions(args, out),
        "interview": lambda: cmd_interview(args, out, inp),
        "eval": lambda: cmd_eval(args, out),
        "connectors": lambda: cmd_connectors(args, out),
        "stop": lambda: cmd_stop(args, out),
        "resume": lambda: cmd_stop(args, out),
        "secret": lambda: cmd_secret(args, out),
        "health": lambda: cmd_health(args, out),
    }
    return handlers[args.command]()


if __name__ == "__main__":
    sys.exit(main())
