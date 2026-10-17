"""The address of the front browser tab, for "tear down this site" (PLAN.md 18.1 item 5).

macOS: one osascript line asks Google Chrome for the URL of the active tab of the front window
(needs the Automation permission Jarvis -> Chrome; T1). Nothing but the URL is read: no title, no
page text. Windows: not supported yet (no UI automation here); the caller says so. The caller
confirms the address on screen before using it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

SCRIPT = 'tell application "Google Chrome" to get URL of active tab of front window'
Runner = Callable[[list[str], float], tuple[int, str, str]]   # argv, timeout -> (code, stdout, stderr)


@dataclass(frozen=True)
class FrontTab:
    url: str | None
    reason: str          # why there is no url, or where it came from


def run_osascript(argv: list[str], timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def front_tab(platform: str | None = None, runner: Runner | None = None, timeout: float = 8.0) -> FrontTab:
    platform = platform or sys.platform
    if platform == "darwin":
        runner = runner or run_osascript
        try:
            code, out, err = runner(["osascript", "-e", SCRIPT], timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return FrontTab(None, f"osascript failed: {type(e).__name__}: {e}")
        if code != 0:
            return FrontTab(None, "Chrome did not answer (is it running, and is Jarvis allowed to control it in "
                                  f"System Settings > Privacy > Automation?): {err.strip()[:160]}")
        url = out.strip().splitlines()[0].strip() if out.strip() else ""
        if not re.match(r"^https?://", url, re.I):
            return FrontTab(None, f"the front tab is not a web page ({url[:60] or 'empty'})")
        return FrontTab(url, "front tab of Google Chrome (osascript)")
    if platform == "win32":
        return FrontTab(None, "reading the front browser tab is not supported yet on Windows; say the address instead")
    return FrontTab(None, f"reading the front browser tab is not supported on {platform}; say the address instead")


def front_tab_url(platform: str | None = None, runner: Runner | None = None) -> str | None:
    return front_tab(platform, runner).url
