"""CLI for workspaces (offices) and teams: jarvis workspace ... | jarvis team ...

A workspace is one office (Sachin's own, "personal", or a company); a team is a group of agents
inside it. Both are YAML files under data/workspaces/<slug>/ (PLAN.md 18.2 step 0, section 27).
Ending one archives it (law 2); nothing is ever deleted from here.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from typing import Callable, TextIO

from jarvis.workspaces.model import PERSONAL, WorkspaceError, slugify
from jarvis.workspaces.store import WorkspaceStore


def register(sub) -> dict[str, Callable]:
    ws = sub.add_parser("workspace", help="offices: list, new, show, edit, archive, unarchive")
    ws.add_argument("action", choices=["list", "new", "show", "edit", "archive", "unarchive"])
    ws.add_argument("slug", nargs="?", default="")
    ws.add_argument("--name", help="new/edit: the office's name")
    ws.add_argument("--brief", help="new/edit: what this office is, in a few lines")
    ws.add_argument("--language", choices=["en", "mr"], help="new/edit: the office's working language")
    ws.add_argument("--duty", action="append", default=None, help="edit: a duty (repeatable); replaces the list")
    ws.add_argument("--project", action="append", default=None, help="edit: a project it owns (repeatable); replaces the list")
    ws.add_argument("--share-personal", choices=["yes", "no"], help="edit: personal memories visible here")
    ws.add_argument("--all", action="store_true", help="list: include archived")

    team = sub.add_parser("team", help="teams inside an office: list, templates, add, show, archive, unarchive")
    team.add_argument("action", choices=["list", "templates", "add", "show", "archive", "unarchive"])
    team.add_argument("workspace", nargs="?", default=PERSONAL, help="workspace slug (default: personal)")
    team.add_argument("team", nargs="?", default="", help="team slug (show, archive, unarchive)")
    team.add_argument("--from", dest="template", help="add: the template to copy (see: jarvis team templates)")
    team.add_argument("--all", action="store_true", help="list: include archived")
    return {"workspace": cmd_workspace, "team": cmd_team}


def _store() -> tuple[WorkspaceStore, object]:
    from jarvis.core.runtime import open_runtime

    rt = open_runtime()
    return WorkspaceStore(rt.paths.home), rt


def _problems(store: WorkspaceStore, out: TextIO) -> None:
    for p in store.problems:
        print(f"  ! {p.path}: {p.error}", file=out)


def cmd_workspace(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    store, rt = _store()
    try:
        if args.action == "list":
            for w in store.list(include_archived=args.all):
                flags = " (archived)" if w.archived else ""
                extra = "" if w.personal else (", personal memories in view" if w.share_personal else ", personal memories out of view")
                print(f"{w.slug:<16} {w.name}{flags}  [{w.kind}, {w.language}{extra}]", file=out)
            _problems(store, out)
            return 0
        if args.action == "new":
            name = (args.name or args.slug or "").strip()
            if not name:
                print("Give a name: jarvis workspace new <slug> --name \"Digital Marketing\"", file=out)
                return 2
            slug = args.slug or slugify(name)
            w = store.create(slug, name, "company", (args.brief or "").strip(), args.language or "mr")
            rt.audit.write("workspace_created", source="cli", workspace=w.slug)
            print(f"Workspace {w.slug} ({w.name}) created: {store.path(w.slug)}", file=out)
            print("Next: jarvis team add " + w.slug + " --from research   (see: jarvis team templates)", file=out)
            return 0
        if not args.slug:
            print("Give a workspace slug (see: jarvis workspace list).", file=out)
            return 2
        if args.action == "show":
            w = store.get(args.slug)
            print(f"{w.name} ({w.slug}){' [archived]' if w.archived else ''}", file=out)
            print(f"kind: {w.kind}   language: {w.language}   personal memories in view: {'yes' if w.share_personal else 'no'}", file=out)
            if w.brief:
                print(f"brief: {w.brief}", file=out)
            print("duties: " + ("; ".join(w.duties) or "(none yet)"), file=out)
            print("projects: " + (", ".join(w.projects) or "(none)"), file=out)
            print("allies: " + (", ".join(w.allies) or "(none)"), file=out)
            print(f"tools: allow {list(w.tools_allow) or 'all'}; deny {list(w.tools_deny) or 'none'}; always ask {list(w.always_ask) or 'none'}", file=out)
            print(f"budget: {w.budget}", file=out)
            from jarvis.control.astra import AstraStore
            from jarvis.control.loka_budget import summary
            print(summary(rt.store.conn, w.slug, w)["line"], file=out)
            regrant = AstraStore(rt.store.conn).needs_regrant(w.slug)
            if regrant:
                print("needs a fresh grant (a check failed): " + ", ".join(x["tool"] for x in regrant), file=out)
            teams = store.teams(args.slug, include_archived=True)
            print("teams: " + (", ".join(f"{t.slug}{' (archived)' if t.archived else ''}" for t in teams) or "(none)"), file=out)
            _problems(store, out)
            return 0
        if args.action == "edit":
            w = store.get(args.slug)
            changes: dict = {}
            if args.name:
                changes["name"] = args.name.strip()
            if args.brief is not None:
                changes["brief"] = args.brief.strip()
            if args.language:
                changes["language"] = args.language
            if args.duty is not None:
                changes["duties"] = tuple(d.strip() for d in args.duty if d.strip())
            if args.project is not None:
                changes["projects"] = tuple(p.strip() for p in args.project if p.strip())
            if args.share_personal:
                changes["share_personal"] = args.share_personal == "yes"
            if not changes:
                print("Nothing to change (use --name, --brief, --language, --duty, --project, --share-personal).", file=out)
                return 2
            store.save(replace(w, **changes))
            rt.audit.write("workspace_edited", source="cli", workspace=w.slug, fields=sorted(changes))
            print(f"Saved {w.slug}: {', '.join(sorted(changes))}.", file=out)
            return 0
        if args.action == "archive":
            w = store.archive(args.slug)
            rt.audit.write("workspace_archived", source="cli", workspace=w.slug)
            print(f"Archived {w.slug}. Its memories and tasks are kept; `jarvis workspace unarchive {w.slug}` reopens it.", file=out)
            return 0
        if args.action == "unarchive":
            w = store.unarchive(args.slug)
            rt.audit.write("workspace_unarchived", source="cli", workspace=w.slug)
            print(f"Reopened {w.slug}.", file=out)
            return 0
        return 2
    except WorkspaceError as e:
        print(f"Error: {e}", file=out)
        return 1
    finally:
        rt.close()


def cmd_team(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    store, rt = _store()
    try:
        if args.action == "templates":
            for t in store.templates():
                roles = ", ".join(m.role for m in t.members)
                print(f"{t.slug:<12} {t.name}: {t.purpose}  [{roles}]", file=out)
            _problems(store, out)
            return 0
        if args.action == "list":
            teams = store.teams(args.workspace, include_archived=args.all)
            for t in teams:
                print(f"{t.slug:<12} {t.name}{' (archived)' if t.archived else ''}: {t.purpose}  "
                      f"[{', '.join(m.name for m in t.members)}]", file=out)
            if not teams:
                print(f"No teams in {args.workspace}. Add one: jarvis team add {args.workspace} --from research", file=out)
            _problems(store, out)
            return 0
        if args.action == "add":
            if not args.template:
                print("Give a template: jarvis team add <workspace> --from research   (see: jarvis team templates)", file=out)
                return 2
            t = store.add_team(args.workspace, template=args.template)
            rt.audit.write("team_added", source="cli", workspace=args.workspace, team=t.slug, template=args.template)
            print(f"Team {t.slug} ({t.name}) added to {args.workspace}: {store.teams_dir(args.workspace) / (t.slug + '.yaml')}", file=out)
            return 0
        if not args.team:
            print("Give a team slug (see: jarvis team list <workspace>).", file=out)
            return 2
        if args.action == "show":
            t = store.team(args.workspace, args.team)
            print(f"{t.name} ({t.slug}){' [archived]' if t.archived else ''}: {t.purpose}", file=out)
            if t.lead_brief:
                print(f"lead: {t.lead_brief}", file=out)
            for m in t.members:
                tools = f" tools: {', '.join(m.tools)}" if m.tools else ""
                print(f"  - {m.name} [{m.role}]{tools}: {m.brief}", file=out)
            print("skills: " + (", ".join(t.skills) or "(none)"), file=out)
            return 0
        if args.action == "archive":
            t = store.archive_team(args.workspace, args.team)
            rt.audit.write("team_archived", source="cli", workspace=args.workspace, team=t.slug)
            print(f"Archived team {t.slug} in {args.workspace}.", file=out)
            return 0
        if args.action == "unarchive":
            t = store.unarchive_team(args.workspace, args.team)
            rt.audit.write("team_unarchived", source="cli", workspace=args.workspace, team=t.slug)
            print(f"Reopened team {t.slug} in {args.workspace}.", file=out)
            return 0
        return 2
    except WorkspaceError as e:
        print(f"Error: {e}", file=out)
        return 1
    finally:
        rt.close()
