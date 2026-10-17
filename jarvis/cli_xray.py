"""CLI for X-ray vision (PLAN.md 18.1): jarvis xray diag | setup | run <url> | last | drill [--live]

diag and setup talk to the kit (jarvis/xray/kit.py); run starts one teardown; last prints the
newest note; drill runs the offline checks (spoken addresses here, fingerprints in
jarvis/xray/drill.py) and, with --live and a ready kit, one real headless teardown of a public page.
"""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis.xray.teardown import TeardownBusy, TeardownError, latest_note, note_summary

LIVE_DRILL_URL = "https://example.com"


def register(sub) -> dict[str, Callable]:
    x = sub.add_parser("xray", help="reverse-engineer a public website's front end: diag, setup, run, last, drill")
    x.add_argument("action", choices=["diag", "setup", "run", "last", "drill"])
    x.add_argument("url", nargs="?", default="", help="run: the site address (https://... or spoken form 'igloo dot inc')")
    x.add_argument("--question", default="", help="run: what to answer (English or Marathi)")
    x.add_argument("--headless", action="store_true", help="run: Chrome without a window")
    x.add_argument("--yes", action="store_true", help="setup: install without asking (scripts only)")
    x.add_argument("--live", action="store_true", help="drill: also run one real headless teardown (kit must be ready)")
    x.add_argument("--provider", default=None, help="run: reasoning provider override (e.g. fake)")
    return {"xray": cmd_xray}


def _print_diag(diag: dict, out: TextIO) -> None:
    print(f"x-ray kit: {'READY' if diag.get('ready') else 'NOT READY'}", file=out)
    for key, value in sorted(diag.items()):
        if key in ("ready", "problems"):
            continue
        print(f"  {key}: {value}", file=out)
    for p in diag.get("problems") or []:
        print(f"  ! {p}", file=out)


def cmd_xray(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None) -> int:
    from jarvis.xray.live import kit_diag

    if args.action == "diag":
        diag = kit_diag()
        _print_diag(diag, out)
        return 0 if diag.get("ready") else 1

    if args.action == "setup":
        try:
            from jarvis.xray.kit import Kit
        except ImportError as e:
            print(f"The x-ray kit module is not available: {e}", file=out)
            return 1
        print("This installs REA (pinned) under ~/.jarvis-tools, outside the repo, with npm.", file=out)
        if not args.yes:
            out.write("Install now? [y/N] ")
            out.flush()
            if inp.readline().strip().lower() not in ("y", "yes", "ho", "हो"):
                print("Not installed.", file=out)
                return 1
        result = Kit().install(confirm=True)
        print(str(result) if result is not None else "Done.", file=out)
        _print_diag(kit_diag(), out)
        return 0

    if args.action == "last":
        path = latest_note(_home())
        if path is None:
            print("No teardown yet. Start one: jarvis xray run <url>", file=out)
            return 1
        print(str(path), file=out)
        print(note_summary(path), file=out)
        return 0

    if args.action == "drill":
        return cmd_drill(args, out)

    # run
    from jarvis.xray.spoken import parse_spoken_address

    url = parse_spoken_address(args.url) or args.url.strip()
    if not url:
        print("Give a site address: jarvis xray run https://igloo.inc --question \"how is the scroll done\"", file=out)
        return 2
    diag = kit_diag()
    if not diag.get("ready"):
        _print_diag(diag, out)
        print("Fix the problems above (jarvis xray setup), then run again.", file=out)
        return 1
    return _run(url, args.question, out, headless=args.headless, provider_override=args.provider)


def _home():
    from jarvis.paths import default_paths

    return default_paths().home


def _run(url: str, question: str, out: TextIO, headless: bool, provider_override: str | None = None) -> int:
    from jarvis.core.runtime import open_runtime
    from jarvis.xray.live import live_deps
    from jarvis.xray.teardown import run_teardown

    rt = open_runtime()
    try:
        try:
            deps = live_deps(rt.paths.home, rt.store, rt.audit, rt.config, memory=rt.memory, headless=headless,
                             provider_override=provider_override)
        except ImportError as e:
            print(f"The x-ray kit is not available: {e}", file=out)
            return 1
        print(f"Teardown of {url} ...", file=out)
        try:
            res = run_teardown(url, question, deps)
        except TeardownBusy as e:
            print(f"Refused: {e}", file=out)
            return 1
        except TeardownError as e:
            print(f"Failed: {e}", file=out)
            return 1
        print(f"Task {res.task_id} {res.state}: {res.note_path}", file=out)
        print(f"Label: {res.label}", file=out)
        print(res.spoken, file=out)
        return 0
    finally:
        rt.close()


def all_offline_checks() -> list:
    """Spoken-address checks (drill_spoken) plus the fingerprint checks (drill.py) when that module exists."""
    from jarvis.xray.drill_spoken import offline_checks

    checks = list(offline_checks())
    try:
        from jarvis.xray import drill as fingerprint_drill
    except ImportError:
        return checks
    more = getattr(fingerprint_drill, "offline_checks", None)
    if callable(more):
        checks.extend(more())
    return checks


def cmd_drill(args: argparse.Namespace, out: TextIO) -> int:
    failed = 0
    for c in all_offline_checks():
        name = getattr(c, "name", None) or (c[0] if isinstance(c, tuple) else str(c))
        ok = getattr(c, "ok", None) if not isinstance(c, tuple) else c[1]
        detail = getattr(c, "detail", "") if not isinstance(c, tuple) else (c[2] if len(c) > 2 else "")
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}{' - ' + str(detail) if detail and not ok else ''}", file=out)
    print(f"offline drill: {'ok' if not failed else f'{failed} check(s) failed'}", file=out)
    if not getattr(args, "live", False):
        return 0 if not failed else 1
    from jarvis.xray.live import kit_diag

    diag = kit_diag()
    if not diag.get("ready"):
        _print_diag(diag, out)
        print("live drill skipped: the kit is not ready", file=out)
        return 1
    code = _run(LIVE_DRILL_URL, "what is it built with", out, headless=True)
    print(f"live drill: {'ok' if code == 0 else 'FAILED'}", file=out)
    return 1 if (failed or code) else 0
