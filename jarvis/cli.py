"""Command line: jarvis init | chat | memory | sessions | interview | eval | stop | resume | secret | health."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import TextIO

from jarvis.config import load_config
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

EXIT_WORDS = {"/exit", "/quit", "exit", "quit"}
PROVIDERS = ["claude_code", "anthropic", "fake"]

CHAT_HELP = """Commands:
  /remember <text>          save a memory now
  /remember-private <text>  save a sensitive memory (kept local, never sent to the cloud)
  /memory <words>           search memories
  /forget <id>              archive a memory
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


def _slash(session: ChatSession, rt: Runtime, text: str, out: TextIO) -> bool:
    """Handle a chat command. Returns False if text is not a command."""
    cmd, _, rest = text.partition(" ")
    rest = rest.strip()
    if cmd in ("/remember", "/remember-private"):
        if session.extractor is None:
            print("Memory is not available.", file=out)
            return True
        try:
            mem = session.extractor.remember(rest, private=cmd == "/remember-private")
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
    return False


def cmd_chat(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    rt = open_runtime()
    try:
        try:
            session = make_chat(rt, args.provider)
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
            if text.startswith("/") and _slash(session, rt, text, out):
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
            print(f"Indexed {mem.reindex()} memory files.", file=out)
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
    mem.add_argument("action", choices=["list", "search", "show", "archive", "export", "reindex", "add"])
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

    ev = sub.add_parser("eval", help="run the migration evaluation suite")
    ev.add_argument("--provider", choices=PROVIDERS, default=None)
    ev.add_argument("--category", default=None)

    stop = sub.add_parser("stop", help="emergency stop: block all model and tool calls")
    stop.add_argument("reason", nargs="*")
    sub.add_parser("resume", help="release the emergency stop")

    sec = sub.add_parser("secret", help="manage secrets in the OS secret store")
    sec.add_argument("action", choices=["set", "status"])
    sec.add_argument("name", nargs="?", default="anthropic_api_key")
    sub.add_parser("health", help="check providers")
    return p


def main(argv: list[str] | None = None, out: TextIO | None = None, inp: TextIO | None = None) -> int:
    if out is None:
        for stream in (sys.stdout, sys.stdin):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")  # Marathi on Windows consoles
    out = out or sys.stdout
    inp = inp or sys.stdin
    args = build_parser().parse_args(argv)
    handlers = {
        "init": lambda: cmd_init(args, out),
        "chat": lambda: cmd_chat(args, out, inp),
        "memory": lambda: cmd_memory(args, out),
        "sessions": lambda: cmd_sessions(args, out),
        "interview": lambda: cmd_interview(args, out, inp),
        "eval": lambda: cmd_eval(args, out),
        "stop": lambda: cmd_stop(args, out),
        "resume": lambda: cmd_stop(args, out),
        "secret": lambda: cmd_secret(args, out),
        "health": lambda: cmd_health(args, out),
    }
    return handlers[args.command]()


if __name__ == "__main__":
    sys.exit(main())
