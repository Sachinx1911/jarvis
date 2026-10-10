"""Computer and media controls for Windows and macOS. No raw shell: fixed commands only.

Apps open only from an allowlist (config `apps`). Volume and media keys use the OS media
keys on Windows and AppleScript on macOS.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.parse
import webbrowser

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
TIMEOUT = 15

DEFAULT_APPS_WINDOWS = {"notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe",
                        "explorer": "explorer.exe"}
DEFAULT_APPS_MAC = {"notes": "Notes", "calculator": "Calculator", "music": "Music", "finder": "Finder",
                    "safari": "Safari"}

# Windows virtual-key codes for media keys.
_VK = {"mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}
_MAC_MEDIA = {
    "mute": "set volume output muted (not output muted of (get volume settings))",
    "volume_down": "set volume output volume ((output volume of (get volume settings)) - 10)",
    "volume_up": "set volume output volume ((output volume of (get volume settings)) + 10)",
    "play_pause": 'tell application "Music" to playpause',
    "next": 'tell application "Music" to next track',
    "previous": 'tell application "Music" to previous track',
}
MEDIA_ACTIONS = tuple(_VK)


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, shell=False)


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class SystemTools:
    def __init__(self, apps: dict[str, str] | None = None, runner=_run, opener=webbrowser.open):
        self.apps = apps if apps is not None else (DEFAULT_APPS_WINDOWS if IS_WINDOWS else DEFAULT_APPS_MAC)
        self.run = runner
        self.open_browser = opener

    def app_names(self) -> list[str]:
        return sorted(self.apps)

    def open_app(self, args: dict) -> str:
        name = args["name"].strip().lower()
        target = self.apps.get(name)
        if not target:
            return f"{name} is not in the allowed apps: {', '.join(self.app_names())}."
        if IS_WINDOWS:
            subprocess.Popen([target], shell=False)  # noqa: S603 (allowlisted executable)
        elif IS_MAC:
            self.run(["open", "-a", target])
        else:
            return "Opening apps is supported on Windows and macOS only."
        return f"Opened {name}."

    def verify_open_app(self, args: dict) -> tuple[bool, str]:
        target = self.apps.get(args["name"].strip().lower(), "")
        if IS_WINDOWS and target:
            out = self.run(["tasklist", "/FI", f"IMAGENAME eq {target}", "/NH"]).stdout.lower()
            ok = target.lower() in out
            return ok, "process running" if ok else "process not found"
        if IS_MAC and target:
            out = self.run(["pgrep", "-x", target]).returncode == 0
            return out, "process running" if out else "process not found"
        return False, "not verifiable here"

    def open_url(self, args: dict) -> str:
        url = args["url"].strip()
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return "Only http(s) links can be opened."
        self.open_browser(url)
        return f"Opened {url} in the browser."

    def notify(self, args: dict) -> str:
        title, message = args.get("title") or "Jarvis", args["message"]
        if IS_MAC:
            script = f'display notification {json_str(message)} with title {json_str(title)}'
            self.run(["osascript", "-e", script])
        elif IS_WINDOWS:
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.Visible = $true; $n.ShowBalloonTip(5000, {_ps_quote(title)}, {_ps_quote(message)}, 'Info'); "
                "Start-Sleep -Seconds 6; $n.Dispose()"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], shell=False)
        else:
            return "Notifications are supported on Windows and macOS only."
        return "Notification shown."

    def media(self, args: dict) -> str:
        action = args["action"]
        times = max(1, min(int(args.get("times", 1)), 10))
        if action not in _VK:
            return f"Unknown media action. Use one of: {', '.join(MEDIA_ACTIONS)}."
        if IS_WINDOWS:
            import ctypes

            for _ in range(times if action.startswith("volume") else 1):
                ctypes.windll.user32.keybd_event(_VK[action], 0, 0, 0)
                ctypes.windll.user32.keybd_event(_VK[action], 0, 2, 0)  # key up
        elif IS_MAC:
            for _ in range(times if action.startswith("volume") else 1):
                self.run(["osascript", "-e", _MAC_MEDIA[action]])
        else:
            return "Media controls are supported on Windows and macOS only."
        return f"Done: {action.replace('_', ' ')}" + (f" x{times}" if action.startswith("volume") and times > 1 else "") + "."

    def brightness(self, args: dict) -> str:
        level = max(0, min(int(args["level"]), 100))
        if not IS_WINDOWS:
            return "Brightness control is supported on Windows laptops only for now."
        ps = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
        r = self.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        return f"Brightness set to {level}%." if r.returncode == 0 else "This screen does not support brightness control."


def json_str(text: str) -> str:
    """AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
