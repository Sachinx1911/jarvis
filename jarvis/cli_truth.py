"""CLI for file truth (PLAN.md 27.12): jarvis verify | jarvis rebuild [--dry-run] [--prune]

The truth of a task, a schedule and a trigger is its file under data/ (jarvis/core/truth.py); the
SQLite rows are an index. `verify` compares the two and exits 1 when they differ. `rebuild`
recreates missing rows from the files (the pralaya test: delete data/jarvis.db, rebuild, same
system). Neither deletes anything (law 2).
"""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis.core.rebuild import rebuild, verify


def register(sub) -> dict[str, Callable]:
    v = sub.add_parser("verify", help="check the database index against the truth files (tasks, schedules, triggers)")
    v.add_argument("--kind", action="append", choices=["tasks", "schedules", "triggers"],
                   help="only this kind (repeatable); default: all")
    r = sub.add_parser("rebuild", help="recreate the database index from the truth files; the file wins where they differ")
    r.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    r.add_argument("--prune", action="store_true",
                   help="a row with no file is first written out as its file, so nothing is lost (rows are never deleted)")
    r.add_argument("--kind", action="append", choices=["tasks", "schedules", "triggers"],
                   help="only this kind (repeatable); default: all")
    return {"verify": cmd_verify, "rebuild": cmd_rebuild}


def _kinds(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.kind) if getattr(args, "kind", None) else ("tasks", "schedules", "triggers")


def cmd_verify(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None) -> int:
    from jarvis.core.runtime import open_runtime

    rt = open_runtime()
    try:
        report = verify(rt.paths.home, rt.store, _kinds(args))
        rt.audit.write("truth_verified", source="cli", ok=report.ok, **report.counts())
    finally:
        rt.close()
    for line in report.lines():
        print(line, file=out)
    return 0 if report.ok else 1


def cmd_rebuild(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None) -> int:
    from jarvis.core.runtime import open_runtime

    rt = open_runtime()
    try:
        report = rebuild(rt.paths.home, rt.store, _kinds(args), dry_run=args.dry_run, prune=args.prune)
        if not args.dry_run:
            rt.audit.write("truth_rebuilt", source="cli", prune=args.prune, **report.counts())
    finally:
        rt.close()
    for line in report.lines():
        print(line, file=out)
    return 0 if report.ok else 1
