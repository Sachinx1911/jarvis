"""CLI for Phase 5: jarvis docs | google | calendar.

Wiring (done by the lead in jarvis/cli.py):
    from jarvis import cli_connectors
    cli_connectors.register(sub)                       # in build_parser()
    handlers.update(cli_connectors.handlers(args, out))  # in main()

Commands:
    jarvis docs index [--project P] [--force]     index new and changed documents
    jarvis docs search <words> [--project P]      search (local terminal: shows private documents too)
    jarvis docs mark <file> --class P1|P2 [--project P]
    jarvis docs list [--project P]
    jarvis google auth | status | logout          auth opens the browser; only when Sachin runs it
    jarvis calendar list [range]                  today, tomorrow, week, a date ...
"""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis.connectors.config import load_connectors_config
from jarvis.connectors.google import auth as google_auth
from jarvis.connectors.google.client import GoogleClient
from jarvis.connectors.google.tools import GoogleTools
from jarvis.connectors.registry import ConnectorDeps, connector_health, default_google_client, doc_library
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.docs.library import DocError
from jarvis.paths import default_paths

# Test hooks: replace with fakes so nothing reaches Google.
GOOGLE_CLIENT_FACTORY: Callable[[dict], Callable[[], GoogleClient | None]] = default_google_client
OAUTH_FLOW_FACTORY: google_auth.FlowFactory | None = None

COMMANDS = ("docs", "google", "calendar")


def register(sub: argparse._SubParsersAction) -> None:
    docs = sub.add_parser("docs", help="project document library: index, search, mark privacy")
    docs.add_argument("action", choices=["index", "search", "mark", "list"])
    docs.add_argument("text", nargs="*", help="search words, or the file to mark")
    docs.add_argument("--project", default=None)
    docs.add_argument("--class", dest="privacy", choices=["P1", "P2"], help="mark: P1 = may go to the cloud model")
    docs.add_argument("--force", action="store_true", help="index: re-read every file")

    g = sub.add_parser("google", help="Google Calendar and Gmail connection")
    g.add_argument("action", choices=["auth", "status", "logout"])

    cal = sub.add_parser("calendar", help="Google Calendar")
    cal.add_argument("action", choices=["list"])
    cal.add_argument("range", nargs="*", help="today (default), tomorrow, week, monday, 2026-10-12 ...")


def handlers(args: argparse.Namespace, out: TextIO) -> dict[str, Callable[[], int]]:
    return {"docs": lambda: cmd_docs(args, out), "google": lambda: cmd_google(args, out),
            "calendar": lambda: cmd_calendar(args, out)}


def _deps() -> ConnectorDeps:
    paths = default_paths()
    paths.ensure()
    # max_privacy P2: this is Sachin's own terminal, nothing here goes to a cloud model.
    return ConnectorDeps(paths.home, Store(paths.db), AuditLog(paths.audit_log), max_privacy="P2",
                         cfg=load_connectors_config())


def cmd_docs(args: argparse.Namespace, out: TextIO) -> int:
    deps = _deps()
    try:
        lib = doc_library(deps)
        if args.action == "index":
            report = lib.index(args.project, force=args.force)
            deps.audit.write("docs_index", project=args.project, added=len(report.added),
                             updated=len(report.updated), removed=len(report.removed), failed=len(report.failed))
            print(f"Indexed: {report.summary()}.", file=out)
            for label, why in report.failed:
                print(f"  failed: {label}: {why}", file=out)
            if not lib.projects():
                print(f"No projects yet. Put approved files in {lib.projects_root}/<project>/docs/.", file=out)
            return 0
        if args.action == "list":
            for d in lib.documents(args.project):
                note = f" ({d.status}: {d.error})" if d.status != "ok" else ""
                print(f"  {d.privacy}  {d.project}/{d.file}  {d.chunks} chunks{note}", file=out)
            return 0
        if args.action == "search":
            query = " ".join(args.text)
            if not query:
                print("Give some words to search for.", file=out)
                return 2
            hits = lib.search(query, project=args.project)
            if not hits:
                print("No matches.", file=out)
            for h in hits:
                print(f"[{h.citation()}] {h.project} {h.privacy}\n  {h.text[:300]}", file=out)
            return 0
        # mark
        if not args.text or not args.privacy:
            print("Usage: jarvis docs mark <file> --class P1|P2 [--project P]", file=out)
            return 2
        project = args.project or _guess_project(lib, args.text[0])
        if not project:
            print("Which project? Add --project <name>.", file=out)
            return 2
        rel = lib.mark(project, " ".join(args.text), args.privacy)
        deps.audit.write("docs_mark", project=project, file=rel, privacy=args.privacy)
        print(f"{project}/{rel} is now {args.privacy}"
              + (" (may be sent to the cloud model)." if args.privacy == "P1" else " (private)."), file=out)
        return 0
    except DocError as e:
        print(f"Error: {e}", file=out)
        return 1
    finally:
        deps.store.close()


def _guess_project(lib, file: str) -> str | None:
    parts = file.replace("\\", "/").split("/")
    if "projects" in parts:
        i = parts.index("projects")
        if len(parts) > i + 2 and parts[i + 2] == "docs":
            return parts[i + 1]
    projects = lib.projects()
    return projects[0] if len(projects) == 1 else None


def cmd_google(args: argparse.Namespace, out: TextIO) -> int:
    cfg = load_connectors_config()
    paths = default_paths()
    audit = AuditLog(paths.audit_log)
    if args.action == "auth":
        print("Opening the browser for Google sign-in (Calendar + Gmail)...", file=out)
        try:
            scopes = google_auth.run_oauth_flow(cfg, OAUTH_FLOW_FACTORY)
        except google_auth.GoogleAuthError as e:
            audit.write("google_auth", ok=False, detail=str(e))
            print(f"Not connected: {e}", file=out)
            return 1
        audit.write("google_auth", ok=True, scopes=[s.rsplit("/", 1)[-1] for s in scopes])
        print("Connected. The login is kept in the OS secret store.", file=out)
        ok, detail = google_auth.token_status(cfg)
        print(f"Token: {detail}", file=out)
        return 0
    if args.action == "logout":
        google_auth.forget_token()
        audit.write("google_logout")
        print("Google login removed from this machine. Also remove Jarvis's access in your Google account "
              "settings if you want to revoke it fully.", file=out)
        return 0
    deps = _deps()
    try:
        for name, ok, detail in connector_health(deps, live=bool(google_auth.load_token())):
            if name.startswith("google"):
                print(f"  {name}: {'OK' if ok else 'NOT OK'} - {detail}", file=out)
    finally:
        deps.store.close()
    return 0


def cmd_calendar(args: argparse.Namespace, out: TextIO) -> int:
    cfg = load_connectors_config()
    tools = GoogleTools(GOOGLE_CLIENT_FACTORY(cfg), cfg, max_privacy="P2")
    print(tools.calendar_list({"range": " ".join(args.range) or "today"}), file=out)
    return 0
