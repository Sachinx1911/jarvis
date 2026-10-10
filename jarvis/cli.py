"""Command line: jarvis init | chat | secret | health."""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import TextIO

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ROUTE, ChatSession
from jarvis.db import Store
from jarvis.paths import default_paths
from jarvis.providers import make_provider
from jarvis.providers.base import ProviderError
from jarvis.routing.policy import RoutingError, decide
from jarvis.secrets import KNOWN_SECRETS, get_secret, set_secret

EXIT_WORDS = {"/exit", "/quit", "exit", "quit"}


def cmd_init(args: argparse.Namespace, out: TextIO) -> int:
    paths = default_paths()
    paths.ensure()
    Store(paths.db).close()
    AuditLog(paths.audit_log).write("init", home=str(paths.home))
    print(f"Jarvis home ready: {paths.home}", file=out)
    return 0


def cmd_chat(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    config = load_config()
    paths = default_paths()
    paths.ensure()
    audit = AuditLog(paths.audit_log)
    try:
        decision = decide(config, ROUTE, args.provider)
    except RoutingError as e:
        print(f"Routing error: {e}", file=out)
        return 2
    store = Store(paths.db)
    session = ChatSession(config, make_provider(decision.provider, config), decision, store, audit)

    def turn(text: str) -> bool:
        try:
            print(f"Jarvis: {session.send(text)}", file=out)
            return True
        except ProviderError as e:
            print(f"Error ({e.kind}): {e}", file=out)
            return False

    try:
        if args.message is not None:
            return 0 if turn(args.message) else 1
        print(f"Jarvis ({decision.provider}/{decision.model}). Type /exit to quit.", file=out)
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
            turn(text)
        return 0
    finally:
        store.close()


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
    for name in ("anthropic", "fake"):
        h = make_provider(name, config).health()
        print(f"{name}: {'OK' if h.ok else 'NOT OK'} - {h.detail}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create folders, database and audit log")
    chat = sub.add_parser("chat", help="chat with Jarvis")
    chat.add_argument("--provider", choices=["anthropic", "fake"], default=None)
    chat.add_argument("-m", "--message", help="send one message and exit")
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
    if args.command == "init":
        return cmd_init(args, out)
    if args.command == "chat":
        return cmd_chat(args, out, inp)
    if args.command == "secret":
        return cmd_secret(args, out)
    return cmd_health(args, out)


if __name__ == "__main__":
    sys.exit(main())
