"""CLI for the isolated browser (Phase 8): setup, site profiles, login, wipe."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from typing import Callable, TextIO

from jarvis.browser.policy import DomainAllowlist, list_profiles, normalize_domain, profile_dir, wipe_profile
from jarvis.paths import default_paths

DOWNLOAD_NOTE = ("This downloads Playwright's own Chromium (about 150-200 MB, into the Playwright cache folder "
                 "of this user). It is separate from your Chrome: no profile, cookies or passwords are shared.")


def register(sub) -> dict[str, Callable]:
    p = sub.add_parser("browser", help="isolated browser: setup, profiles, login, wipe")
    p.add_argument("action", choices=["setup", "profiles", "login", "wipe"])
    p.add_argument("site", nargs="?", default="", help="site name for login/wipe, e.g. shop.example")
    p.add_argument("url", nargs="?", default="", help="login page (default: https://<site>/)")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    return {"browser": cmd_browser}


def _confirm(question: str, args: argparse.Namespace, out: TextIO, inp: TextIO) -> bool:
    if args.yes:
        return True
    print(f"{question} [y/N] ", end="", file=out, flush=True)
    return inp.readline().strip().lower() in ("y", "yes")


def cmd_browser(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    home = default_paths().home
    if args.action == "setup":
        if importlib.util.find_spec("playwright") is None:
            print("Playwright is not installed. First: pip install playwright", file=out)
            return 1
        print(DOWNLOAD_NOTE, file=out)
        if not _confirm("Download Chromium for Jarvis now?", args, out, inp):
            print("Nothing downloaded.", file=out)
            return 0
        return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])

    if args.action == "profiles":
        rows = list_profiles(home)
        for name, size in rows:
            print(f"{name}  ({size // 1024} KB)", file=out)
        if not rows:
            print("No site profiles. Create one with: jarvis browser login <site>", file=out)
        return 0

    if not args.site:
        print("Give a site name, e.g. jarvis browser login shop.example", file=out)
        return 1
    try:
        site = normalize_domain(args.site)
    except ValueError as e:
        print(str(e), file=out)
        return 1

    if args.action == "wipe":
        if not _confirm(f"Delete the browser profile for {site} (cookies and logins)?", args, out, inp):
            print("Kept.", file=out)
            return 0
        print(f"Deleted the profile for {site}." if wipe_profile(home, site) else f"No profile for {site}.", file=out)
        return 0

    # login: the user logs in himself in a visible window; Jarvis types nothing.
    from jarvis.browser.playwright_driver import login_interactive
    from jarvis.browser.policy import BrowserError

    url = args.url or f"https://{site}/"
    if not DomainAllowlist([site]).allows(url):
        print(f"{url} is not on {site}.", file=out)
        return 1
    print(f"Opening {url} in Jarvis's browser profile for {site}. Log in yourself, then close the window.", file=out)
    try:
        # Sign-in may pass through another domain (single sign-on); the user drives this window.
        login_interactive(profile_dir(home, site), url, lambda u: u.startswith(("https://", "http://", "about:")))
    except BrowserError as e:
        print(str(e), file=out)
        return 1
    print(f"Saved. Tasks that use the {site} profile will be logged in.", file=out)
    return 0
