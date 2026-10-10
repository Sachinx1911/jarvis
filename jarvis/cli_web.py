"""CLI for Phase 7: `jarvis dashboard [--port 8765] [--open] [--new-token]`."""

from __future__ import annotations

import argparse
from typing import Callable, TextIO

from jarvis.web.settings import STATIC_DIR, get_or_create_token, is_loopback, load_web_settings


def register(sub) -> dict[str, Callable]:
    p = sub.add_parser("dashboard", help="start the local web dashboard (127.0.0.1 only)")
    p.add_argument("--port", type=int, default=None, help="port (default from config/web.yaml, 8765)")
    p.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    p.add_argument("--new-token", action="store_true", help="replace the dashboard access token")
    return {"dashboard": cmd_dashboard}


def dashboard_url(port: int, token: str) -> str:
    # The token goes in the URL fragment: browsers never send it to the server or into logs.
    return f"http://127.0.0.1:{port}/#token={token}"


def cmd_dashboard(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    settings = load_web_settings()
    if args.port:
        settings.port = args.port
    if not is_loopback(settings.host):
        print(f"Refusing to listen on {settings.host}: the dashboard is for this computer only (127.0.0.1).", file=out)
        return 2
    settings.host = "127.0.0.1"
    try:
        token = get_or_create_token(rotate=args.new_token)
    except Exception as e:  # no OS secret store available
        print(f"Could not read or save the dashboard token in the OS secret store: {e}", file=out)
        return 1

    import uvicorn

    from jarvis.web.app import create_app

    app = create_app(settings, token)
    url = dashboard_url(settings.port, token)
    if not (STATIC_DIR / "index.html").exists():
        print("Note: the web page is not built yet (cd dashboard; npm install; npm run build). The API works.", file=out)
    print(f"Jarvis dashboard: {url}", file=out)
    print("Keep this link private: the token in it gives full control of Jarvis. Ctrl+C to stop.", file=out)
    out.flush()
    if args.open:
        import webbrowser

        webbrowser.open(url)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", proxy_headers=False,
                server_header=False)
    return 0
