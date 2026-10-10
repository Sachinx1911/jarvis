"""CLI for memory upkeep: `jarvis memory-maint run|report [--dry-run]` (PLAN.md 6.6).

Integration (jarvis/cli.py, build_parser_with_extensions): add cli_memory to the modules
whose register(sub) returns {command: handler}:
    for module in (cli_tasks, cli_browser, cli_web, cli_memory):
        extra.update(module.register(sub))
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Callable, TextIO

from jarvis.core.runtime import open_runtime
from jarvis.memory.maintenance import MemoryCleanup, latest_report
from jarvis.memory.upkeep_settings import load_memory_settings


def register(sub) -> dict[str, Callable]:
    mm = sub.add_parser("memory-maint", help="weekly memory cleanup: duplicates, relative dates, unused memories")
    mm.add_argument("action", choices=["run", "report"], help="run: clean up now; report: show the last report")
    mm.add_argument("--dry-run", action="store_true", help="show what would change; change nothing")
    return {"memory-maint": cmd_memory_maint}


def cmd_memory_maint(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None,
                     today: date | None = None) -> int:
    rt = open_runtime()
    try:
        if args.action == "report":
            path = latest_report(rt.paths.home)
            if path is None:
                print("No cleanup report yet. Run: jarvis memory-maint run --dry-run", file=out)
                return 1
            print(path.read_text(encoding="utf-8"), file=out)
            return 0
        settings = dict(load_memory_settings().get("cleanup") or {})
        report = MemoryCleanup(rt.memory, rt.paths.home, today or date.today(), rt.audit, settings).run(
            dry_run=args.dry_run)
        print(report.summary(), file=out)
        if report.path:
            print(f"Report: {report.path}", file=out)
        return 1 if report.errors else 0
    finally:
        rt.close()
