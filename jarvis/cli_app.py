"""CLI: `jarvis app [--port N] [--no-browser] [--url] [--install-shortcut] [--autostart on|off]`.

Wiring (jarvis/cli.py, build_parser_with_extensions): add cli_app to the modules whose
register(sub) result is merged into `extra`. Also runs on its own, which is what the
Desktop shortcut uses: `pythonw -m jarvis.cli_app`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, TextIO

from jarvis import app_launcher


def register(sub) -> dict[str, Callable]:
    p = sub.add_parser("app", help="start Jarvis in one click: dashboard + scheduler (+ Telegram if set up)")
    p.add_argument("--port", type=int, default=None, help="port (default from config/web.yaml, 8765)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--url", action="store_true",
                   help="print the dashboard link (with its access token) and exit; used by the Mac app")
    p.add_argument("--install-shortcut", action="store_true",
                   help="put a 'Jarvis' shortcut on the Desktop (Windows; macOS: Jarvis.command)")
    p.add_argument("--autostart", choices=["on", "off"], default=None,
                   help="start Jarvis when you log in (off by default)")
    return {"app": cmd_app}


def cmd_app(args: argparse.Namespace, out: TextIO | None, inp: TextIO | None, approver_factory) -> int:
    def say(text: str) -> None:
        if out is not None:
            print(text, file=out, flush=True)

    if args.install_shortcut or args.autostart:
        try:
            if args.install_shortcut:
                path = app_launcher.install_shortcut()
                say(f"Shortcut created: {path}. Double-click 'Jarvis' to start it.")
            if args.autostart:
                path = app_launcher.set_autostart(args.autostart == "on")
                say(f"Start at login is {args.autostart.upper()} ({path}).")
        except (RuntimeError, OSError) as e:
            say(f"Could not change the shortcut: {e}")
            return 1
        return 0
    if args.url:
        return print_url(say, args.port)
    return app_launcher.run_app(out, open_browser=not args.no_browser, port=args.port)


def print_url(say: Callable[[str], None], port: int | None = None) -> int:
    """One line: the local dashboard link with its token (the port of a running Jarvis if any)."""
    from jarvis.app_launcher import InstanceLock
    from jarvis.cli_web import dashboard_url
    from jarvis.paths import default_paths
    from jarvis.web.settings import get_or_create_token, load_web_settings

    settings = load_web_settings()
    running = InstanceLock(default_paths().data).read_info().get("port")
    try:
        token = get_or_create_token()
    except Exception as e:  # noqa: BLE001 (keyring backends raise many kinds)
        say(f"Could not read the dashboard token from the OS secret store: {e}")
        return 1
    say(dashboard_url(int(port or running or settings.port), token))
    return 0


def _log_stream():
    """pythonw has no console (sys.stdout is None): write to data/app.log instead."""
    from jarvis.paths import default_paths

    paths = default_paths()
    paths.data.mkdir(parents=True, exist_ok=True)
    return open(paths.data / "app.log", "a", encoding="utf-8", buffering=1)


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None or sys.stderr is None:
        log = _log_stream()
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    for stream in (sys.stdout,):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command")
    handlers = register(sub)
    args = p.parse_args(["app", *(sys.argv[1:] if argv is None else argv)])
    return handlers["app"](args, sys.stdout, sys.stdin, lambda: None)


if __name__ == "__main__":
    sys.exit(main())
