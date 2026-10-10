"""CLI for local backups: `jarvis backup create | list | restore-check [archive|latest]`.

Integration (jarvis/cli.py, build_parser_with_extensions): add cli_backup to the modules
whose register(sub) returns {command: handler}:
    for module in (cli_tasks, cli_browser, cli_web, cli_memory, cli_app, cli_approvals, cli_india, cli_backup):
        extra.update(module.register(sub))
"""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis import backup
from jarvis.control.audit import AuditLog
from jarvis.paths import CONFIG_DIR, default_paths

MAX_PROBLEMS_SHOWN = 20


def register(sub) -> dict[str, Callable]:
    p = sub.add_parser("backup", help="local dated backups of personal data: create, list, restore-check")
    p.add_argument("action", choices=["create", "list", "restore-check"],
                   help="create: new archive; list: archives in the backup folder; "
                        "restore-check: verify an archive in a temporary folder (live data untouched)")
    p.add_argument("archive", nargs="?", default="latest",
                   help="restore-check: archive path or file name, or 'latest' (default)")
    return {"backup": cmd_backup}


def cmd_backup(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None) -> int:
    paths = default_paths()
    audit = AuditLog(paths.audit_log)
    try:
        settings = backup.load_backup_settings(CONFIG_DIR)
        if args.action == "create":
            return _create(paths.home, settings, audit, out)
        if args.action == "list":
            return _list(settings, out)
        return _restore_check(args.archive, settings, audit, out)
    except backup.BackupError as e:
        print(f"Backup error: {e}", file=out)
        return 1
    except OSError as e:
        print(f"Backup error: {e.strerror or e}", file=out)
        return 1


def _create(home, settings: backup.BackupSettings, audit: AuditLog, out: TextIO) -> int:
    r = backup.create_backup(home, settings, audit, CONFIG_DIR)
    print(f"Backup created: {r.path}", file=out)
    dbs = f" (incl. {len(r.databases)} database snapshot{'s' if len(r.databases) != 1 else ''})" if r.databases else ""
    print(f"  {r.files} files{dbs}, {backup.human_size(r.data_bytes)} of data, "
          f"archive {backup.human_size(r.archive_bytes)}", file=out)
    if r.excluded:
        print("  Left out: " + ", ".join(f"{reason} ({n})" for reason, n in r.excluded.items()), file=out)
    if r.pruned:
        print(f"  Removed {len(r.pruned)} old backup(s) (keep_last {settings.keep_last}): "
              + ", ".join(r.pruned), file=out)
    for warning in r.warnings:
        print(f"  Warning: {warning}", file=out)
    print("  Note: archives are not encrypted yet. Keep this folder private "
          "(final backup location: open decision #10 in PLAN.md).", file=out)
    return 0


def _list(settings: backup.BackupSettings, out: TextIO) -> int:
    dest = backup.check_destination(settings.destination)
    items = backup.list_backups(dest)
    if not items:
        print(f"No backups in {dest} yet. Run: jarvis backup create", file=out)
        return 0
    print(f"Backups in {dest} (newest first, keep_last {settings.keep_last}):", file=out)
    for item in items:
        files = f"{item.files} files" if item.files is not None else "? files"
        state = "manifest ok" if item.manifest_ok else f"MANIFEST UNREADABLE: {item.note}"
        print(f"  {item.created}  {backup.human_size(item.size):>9}  {files:>11}  {state}  {item.path.name}",
              file=out)
    return 0


def _restore_check(arg: str, settings: backup.BackupSettings, audit: AuditLog, out: TextIO) -> int:
    dest = backup.check_destination(settings.destination) if arg == "latest" else _optional_dest(settings)
    archive = backup.find_archive(arg, dest)
    r = backup.restore_check(archive, audit)
    print(f"restore-check {archive.name}: {'OK' if r.ok else 'FAILED'}", file=out)
    if r.created_at:
        commit = (r.code_commit or "unknown")[:12]
        print(f"  created {r.created_at}, code commit {commit}", file=out)
    print(f"  {r.files_checked} files extracted and checked against the manifest", file=out)
    for rel, state in r.databases.items():
        print(f"  database {rel}: integrity {state}", file=out)
    if not r.databases:
        print("  no database in this archive", file=out)
    tasks = r.tasks if r.tasks is not None else "n/a"
    print(f"  memory files: {r.memory_files}, projects: {r.projects}, task rows: {tasks}", file=out)
    for problem in r.problems[:MAX_PROBLEMS_SHOWN]:
        print(f"  Problem: {problem}", file=out)
    if len(r.problems) > MAX_PROBLEMS_SHOWN:
        print(f"  ... and {len(r.problems) - MAX_PROBLEMS_SHOWN} more problems", file=out)
    print("  Live data was not touched (checked in a temporary folder, now deleted).", file=out)
    return 0 if r.ok else 1


def _optional_dest(settings: backup.BackupSettings):
    """For a named archive: the backup folder if the config is valid, else only the given path."""
    try:
        return backup.check_destination(settings.destination)
    except backup.BackupError:
        return None
