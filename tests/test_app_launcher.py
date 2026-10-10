"""`jarvis app`: register() pattern, single-instance lock, one process with the dashboard
and the scheduler, shortcuts and autostart (no real shortcut, server or browser)."""

import argparse
import io
import plistlib
import subprocess

import pytest

pytest.importorskip("fastapi")

from jarvis import app_launcher, cli_app  # noqa: E402
from jarvis.app_launcher import InstanceLock  # noqa: E402


def _parse(argv):
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    handlers = cli_app.register(sub)
    return p.parse_args(argv), handlers


def test_register_returns_handler():
    args, handlers = _parse(["app", "--no-browser", "--port", "9100", "--autostart", "off"])
    assert set(handlers) == {"app"} and args.no_browser and args.port == 9100 and args.autostart == "off"
    args, _ = _parse(["app"])
    assert args.autostart is None and not args.install_shortcut


def test_single_instance_lock(isolated):
    data = isolated / "data"
    a, b = InstanceLock(data), InstanceLock(data)
    assert a.acquire()
    a.write_info(9123)
    assert not b.acquire()  # a second start sees the running copy
    assert b.read_info()["port"] == 9123
    a.release()
    assert b.acquire()
    b.release()


class FakeServer:
    def __init__(self, config):
        self.config = config
        self.started = True
        self.should_exit = False
        self.ran = False

    def run(self):
        self.ran = True


class FakeService:
    def __init__(self):
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def catch_up(self):
        return []

    def shutdown(self):
        self.stopped = True


class FakeProactive:
    def __init__(self):
        self.svc = FakeService()

    def ensure_default_schedules(self):
        return []

    def service(self):
        return self.svc

    def fire_reminders(self):
        return 0


def test_run_app_starts_dashboard_and_scheduler_then_stops(isolated):
    servers, opened, p = [], [], FakeProactive()

    def factory(config):
        servers.append(FakeServer(config))
        return servers[-1]

    out = io.StringIO()
    code = app_launcher.run_app(out, open_browser=True, port=9124, browser=opened.append, server_factory=factory,
                                proactive_factory=lambda: p)
    assert code == 0 and servers[0].ran
    assert servers[0].config.host == "127.0.0.1" and servers[0].config.port == 9124
    assert p.svc.started and p.svc.stopped  # graceful shutdown stops the scheduler
    assert "Scheduler running" in out.getvalue()
    lock = InstanceLock(isolated / "data")
    assert lock.acquire()  # released after the run
    lock.release()
    log = (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "app_started" in log and "app_stopped" in log


def test_second_start_only_opens_the_browser(isolated):
    from jarvis.secrets import get_secret
    from jarvis.web.settings import get_or_create_token

    token = get_or_create_token()
    held = InstanceLock(isolated / "data")
    assert held.acquire()
    held.write_info(9125)
    opened, servers = [], []
    code = app_launcher.run_app(io.StringIO(), browser=opened.append, server_factory=lambda c: servers.append(c),
                                proactive_factory=FakeProactive)
    held.release()
    assert code == 0 and servers == []  # no second server
    assert opened == [f"http://127.0.0.1:9125/#token={token}"] and get_secret("dashboard_token") == token


def test_quit_button_stops_the_server(isolated):
    seen = {}

    class QuitServer(FakeServer):
        def run(self):
            ctx = self.config.app.state.ctx  # what POST /api/app/quit calls
            seen["scheduler_running"] = ctx.extra["scheduler_running"]
            ctx.on_quit()
            seen["should_exit"] = self.should_exit

    code = app_launcher.run_app(io.StringIO(), open_browser=False, port=9126, server_factory=QuitServer,
                                proactive_factory=FakeProactive)
    assert code == 0 and seen == {"scheduler_running": True, "should_exit": True}


def test_non_loopback_refused(isolated, monkeypatch):
    from jarvis.web import settings as web_settings

    monkeypatch.setattr(web_settings, "load_web_settings", lambda: web_settings.WebSettings(host="0.0.0.0"))
    out = io.StringIO()
    assert app_launcher.run_app(out, server_factory=FakeServer, proactive_factory=FakeProactive) == 2
    assert "Refusing" in out.getvalue()


def test_windows_shortcut_uses_powershell_with_env_values(tmp_path):
    calls = []

    def run(argv, env, **kw):
        calls.append((argv, env))
        return subprocess.CompletedProcess(argv, 0, stdout=r"C:\Users\x\Desktop\Jarvis.lnk" + "\n", stderr="")

    py = tmp_path / "pythonw.exe"
    path = app_launcher.install_shortcut(platform="win32", run=run, python=py)
    argv, env = calls[0]
    assert argv[0] == "powershell.exe" and "-NoProfile" in argv and "WScript.Shell" in argv[-1]
    assert env["JARVIS_SC_FOLDER"] == "Desktop" and env["JARVIS_SC_TARGET"] == str(py)
    assert env["JARVIS_SC_ARGS"] == "-m jarvis.cli_app" and env["JARVIS_SC_REMOVE"] == "0"
    assert str(py) not in argv[-1]  # values are never pasted into the script
    assert path.name == "Jarvis.lnk"

    app_launcher.set_autostart(True, platform="win32", run=run, python=py)
    assert calls[-1][1]["JARVIS_SC_FOLDER"] == "Startup" and "--no-browser" in calls[-1][1]["JARVIS_SC_ARGS"]
    app_launcher.set_autostart(False, platform="win32", run=run, python=py)
    assert calls[-1][1]["JARVIS_SC_REMOVE"] == "1"


def test_windows_shortcut_failure_is_reported(tmp_path):
    def run(argv, env, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="COM error")

    with pytest.raises(RuntimeError, match="COM error"):
        app_launcher.install_shortcut(platform="win32", run=run, python=tmp_path / "pythonw.exe")


def test_mac_shortcut_and_launch_agent(tmp_path):
    py = tmp_path / "venv" / "bin" / "python"
    cmd = app_launcher.install_shortcut(platform="darwin", home=tmp_path, python=py)
    assert cmd == tmp_path / "Desktop" / "Jarvis.command"
    assert f'"{py}" -m jarvis.cli_app' in cmd.read_text(encoding="utf-8")
    agent = app_launcher.set_autostart(True, platform="darwin", home=tmp_path, python=py)
    plist = plistlib.loads(agent.read_bytes())
    assert plist["ProgramArguments"] == [str(py), "-m", "jarvis.cli_app", "--no-browser"] and plist["RunAtLoad"]
    app_launcher.set_autostart(False, platform="darwin", home=tmp_path, python=py)
    assert not agent.exists()


def test_other_platforms_refused(tmp_path):
    with pytest.raises(RuntimeError):
        app_launcher.install_shortcut(platform="linux", home=tmp_path, python=tmp_path / "python")


def test_cli_shortcut_option_does_not_start_the_app(monkeypatch):
    made, started = [], []
    monkeypatch.setattr(app_launcher, "install_shortcut", lambda: made.append(1) or "Jarvis.lnk")
    monkeypatch.setattr(app_launcher, "run_app", lambda *a, **k: started.append(1) or 0)
    args, handlers = _parse(["app", "--install-shortcut"])
    out = io.StringIO()
    assert handlers["app"](args, out, io.StringIO(), lambda: None) == 0
    assert made == [1] and started == [] and "Shortcut created" in out.getvalue()


def test_launcher_python_prefers_pythonw(tmp_path):
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    assert app_launcher.launcher_python("win32", str(tmp_path / "python.exe")).name == "pythonw.exe"
    assert app_launcher.launcher_python("darwin", str(tmp_path / "python.exe")).name == "python.exe"
