"""`jarvis app`: one process, one click.

Starts, together:
- the dashboard server (127.0.0.1 only, the same token security as `jarvis dashboard`),
- the proactive scheduler (schedules, reminders, heartbeat, brief), like `jarvis daemon`,
- the Telegram bot, only when its token and allowed user id are configured,
then opens the browser. A second start does not start a second copy: it only opens the
browser on the running one (single-instance lock in data/app.lock).

Shortcuts: `--install-shortcut` puts "Jarvis" on the Desktop; `--autostart on|off` starts
Jarvis at login (off by default; Sachin's choice). Windows uses a .lnk made with
WScript.Shell pointing at the venv's pythonw.exe (no console window). macOS (behind a
platform guard): a Jarvis.command file on the Desktop and a LaunchAgent plist.
"""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, TextIO

from jarvis.control.audit import AuditLog
from jarvis.paths import REPO_ROOT, default_paths

APP_MODULE = "jarvis.cli_app"
LAUNCH_AGENT_LABEL = "com.jarvis.app"


# ---- single instance ----

class InstanceLock:
    """An OS file lock on data/app.lock, held while the app runs. The OS drops it when the
    process ends, even after a crash, so a stale lock never blocks the next start.
    The port and pid of the running copy are kept next to it in data/app.json."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "app.lock"
        self.info_path = data_dir / "app.json"
        self._fh: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def write_info(self, port: int) -> None:
        self.info_path.write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")

    def read_info(self) -> dict[str, Any]:
        try:
            data = json.loads(self.info_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self.info_path.unlink(missing_ok=True)
        finally:
            self._fh.close()
            self._fh = None


# ---- shortcuts and autostart ----

def launcher_python(platform: str = sys.platform, executable: str = sys.executable) -> Path:
    """The venv's pythonw.exe on Windows (no console window), else the running python."""
    exe = Path(executable)
    if platform == "win32":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return w
    return exe


_PS_SHORTCUT = r"""
$ErrorActionPreference = 'Stop'
$folder = [Environment]::GetFolderPath($env:JARVIS_SC_FOLDER)
$path = Join-Path $folder 'Jarvis.lnk'
if ($env:JARVIS_SC_REMOVE -eq '1') {
  if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
  Write-Output $path
  exit 0
}
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($path)
$s.TargetPath = $env:JARVIS_SC_TARGET
$s.Arguments = $env:JARVIS_SC_ARGS
$s.WorkingDirectory = $env:JARVIS_SC_DIR
$s.Description = 'Jarvis personal assistant'
$s.Save()
Write-Output $path
"""


def _windows_shortcut(folder: str, args: str, remove: bool = False, run: Callable = subprocess.run,
                      python: Path | None = None) -> Path:
    """Create (or remove) Jarvis.lnk in a special folder ('Desktop' or 'Startup').
    Values go to PowerShell as environment variables, never pasted into the script text."""
    env = dict(os.environ)
    env.update({"JARVIS_SC_FOLDER": folder, "JARVIS_SC_TARGET": str(python or launcher_python()),
                "JARVIS_SC_ARGS": args, "JARVIS_SC_DIR": str(REPO_ROOT), "JARVIS_SC_REMOVE": "1" if remove else "0"})
    res = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
               _PS_SHORTCUT], env=env, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or "PowerShell failed").strip()[:500])
    out = (res.stdout or "").strip().splitlines()[-1]
    return Path(out) if os.name == "nt" else PureWindowsPath(out)  # PowerShell prints a Windows path


def _mac_command_file(home: Path, python: Path) -> Path:
    path = home / "Desktop" / "Jarvis.command"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/bash\ncd "{REPO_ROOT}" && exec "{python}" -m {APP_MODULE}\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def launch_agent_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def install_shortcut(platform: str = sys.platform, run: Callable = subprocess.run, home: Path | None = None,
                     python: Path | None = None) -> Path:
    python = python or launcher_python(platform)
    if platform == "win32":
        return _windows_shortcut("Desktop", f"-m {APP_MODULE}", run=run, python=python)
    if platform == "darwin":
        return _mac_command_file(home or Path.home(), python)
    raise RuntimeError("desktop shortcuts are made on Windows and macOS only")


def set_autostart(on: bool, platform: str = sys.platform, run: Callable = subprocess.run,
                  home: Path | None = None, python: Path | None = None) -> Path:
    python = python or launcher_python(platform)
    if platform == "win32":
        return _windows_shortcut("Startup", f"-m {APP_MODULE} --no-browser", remove=not on, run=run, python=python)
    if platform == "darwin":
        path = launch_agent_path(home or Path.home())
        if not on:
            path.unlink(missing_ok=True)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        log = str(default_paths().data / "app.log")
        plist = {"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": [str(python), "-m", APP_MODULE, "--no-browser"],
                 "WorkingDirectory": str(REPO_ROOT), "RunAtLoad": True, "KeepAlive": False,
                 "StandardOutPath": log, "StandardErrorPath": log}
        path.write_bytes(plistlib.dumps(plist))
        return path
    raise RuntimeError("autostart is set up on Windows and macOS only")


# ---- background services ----

class Background:
    """The proactive scheduler and (if configured) the Telegram bot, started and stopped together."""

    def __init__(self, out: TextIO | None, audit: AuditLog, provider: str | None = None,
                 proactive_factory: Callable[[], Any] | None = None, telegram: bool = True):
        self.out = out
        self.audit = audit
        self.provider = provider
        self.proactive_factory = proactive_factory
        self.want_telegram = telegram
        self.svc: Any = None
        self.telegram_running = False
        self._tg_stop: Callable[[], None] | None = None

    def _say(self, text: str) -> None:
        if self.out is not None:
            print(text, file=self.out, flush=True)

    def _telegram_parts(self, settings):
        from jarvis.secrets import get_secret

        token = get_secret(settings.telegram_secret)
        uid = settings.telegram_user_id
        return (token, uid) if token and uid else (None, None)

    def start(self) -> None:
        if self.proactive_factory is not None:
            p = self.proactive_factory()
            token = uid = None
        else:
            from jarvis.proactive.notify import make_notifier
            from jarvis.proactive.service import Proactive
            from jarvis.proactive.settings import load_settings

            settings = load_settings()
            p = Proactive(settings, notifier=make_notifier(settings, self.audit, self.out),
                          provider_override=self.provider)
            token, uid = self._telegram_parts(settings) if self.want_telegram else (None, None)
        added = p.ensure_default_schedules()
        if added:
            self._say(f"Created default schedules: {', '.join(added)} (pause them in the Schedules tab).")
        self.svc = p.service()
        self.svc.start()

        def catch_up() -> None:  # may call a model: keep it off the start-up path
            try:
                for r in self.svc.catch_up():
                    self._say(f"Catch-up run {r.schedule_id}: {r.status}")
                p.fire_reminders()
            except Exception as e:
                self.audit.write("app_catch_up_error", error=f"{type(e).__name__}: {e}")

        threading.Thread(target=catch_up, name="jarvis-catch-up", daemon=True).start()
        self._say("Scheduler running.")
        if token and uid:
            self._start_telegram(p, uid, token)
        else:
            self._say("Telegram: not set up (Setup tab), so the bot is off.")

    def _start_telegram(self, p, uid: int, token: str) -> None:
        from telegram import Update

        from jarvis.telegram.bot import JarvisBot
        from jarvis.telegram.core import BotCore

        timeout = float(p.settings.section("telegram").get("approval_timeout_seconds", 300))
        bot = JarvisBot(BotCore(p, uid), timeout)
        application = bot.build(token)
        holder: dict[str, Any] = {}

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            holder["loop"] = loop
            try:
                # stop_signals=None: signals belong to the main thread (the web server).
                application.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)
            except Exception as e:
                self.audit.write("app_telegram_error", error=type(e).__name__)
            finally:
                self.telegram_running = False
                try:
                    bot.close()
                except Exception:
                    pass

        t = threading.Thread(target=run, name="jarvis-telegram", daemon=True)
        t.start()
        self.telegram_running = True
        self._say("Telegram bot running.")

        def stop() -> None:
            loop = holder.get("loop")
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(application.stop_running)
            t.join(15)

        self._tg_stop = stop

    def stop(self) -> None:
        if self._tg_stop is not None:
            try:
                self._tg_stop()
            except Exception:
                pass
        if self.svc is not None:
            try:
                self.svc.shutdown()
            except Exception:
                pass


# ---- the app ----

def run_app(out: TextIO | None, open_browser: bool = True, port: int | None = None, *,
            browser: Callable[[str], Any] = webbrowser.open, server_factory: Callable | None = None,
            proactive_factory: Callable[[], Any] | None = None, background: bool = True) -> int:
    from jarvis.cli_web import dashboard_url
    from jarvis.web.settings import STATIC_DIR, get_or_create_token, is_loopback, load_web_settings

    def say(text: str) -> None:
        if out is not None:
            print(text, file=out, flush=True)

    settings = load_web_settings()
    if port:
        settings.port = port
    if not is_loopback(settings.host):
        say(f"Refusing to listen on {settings.host}: Jarvis is for this computer only (127.0.0.1).")
        return 2
    settings.host = "127.0.0.1"
    paths = default_paths()
    paths.ensure()
    audit = AuditLog(paths.audit_log)
    try:
        token = get_or_create_token()
    except Exception as e:  # no OS secret store
        say(f"Could not read or save the dashboard token in the OS secret store: {e}")
        return 1

    lock = InstanceLock(paths.data)
    if not lock.acquire():
        running_port = int(lock.read_info().get("port") or settings.port)
        say(f"Jarvis is already running on port {running_port}; opening it.")
        browser(dashboard_url(running_port, token))
        return 0

    services = Background(out, audit, settings.provider, proactive_factory) if background else None
    try:
        import uvicorn

        from jarvis.web.app import create_app

        holder: dict[str, Any] = {}
        extra: dict[str, Any] = {"scheduler_running": False, "telegram_running": False}

        def quit_app() -> None:
            server = holder.get("server")
            if server is not None:
                server.should_exit = True

        app = create_app(settings, token, on_quit=quit_app, extra=extra)
        config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning",
                                proxy_headers=False, server_header=False)
        server = (server_factory or uvicorn.Server)(config)
        holder["server"] = server
        lock.write_info(settings.port)
        if services is not None:
            try:
                services.start()
                extra["scheduler_running"] = True
                extra["telegram_running"] = services.telegram_running
            except Exception as e:  # the dashboard still starts; the Setup tab shows the state
                audit.write("app_scheduler_error", error=f"{type(e).__name__}: {e}")
                say(f"Scheduler not started: {type(e).__name__}: {e}")
        url = dashboard_url(settings.port, token)
        if not (STATIC_DIR / "index.html").exists():
            say("Note: the web page is not built yet (cd dashboard; npm install; npm run build). The API works.")
        say(f"Jarvis is running: http://127.0.0.1:{settings.port}/  (Ctrl+C or the Quit button to stop)")
        audit.write("app_started", port=settings.port, scheduler=extra["scheduler_running"],
                    telegram=extra["telegram_running"])

        if open_browser:
            def open_when_ready() -> None:
                for _ in range(200):
                    if getattr(server, "started", False):
                        break
                    time.sleep(0.1)
                browser(url)

            threading.Thread(target=open_when_ready, name="jarvis-open-browser", daemon=True).start()
        try:
            server.run()
        except SystemExit:  # uvicorn exits like this when the port is taken
            say(f"Could not start on port {settings.port} (is it in use?). Try: jarvis app --port 8770")
            return 1
        return 0
    finally:
        if services is not None:
            services.stop()
        audit.write("app_stopped")
        lock.release()
