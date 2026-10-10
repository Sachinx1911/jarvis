"""`jarvis dashboard`: register() pattern, loopback only, URL with the token in the fragment."""

import argparse
import io

import pytest

pytest.importorskip("fastapi")

from jarvis import cli_web  # noqa: E402
from jarvis.web.settings import WebSettings, is_loopback  # noqa: E402


def _parse(argv):
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    handlers = cli_web.register(sub)
    return p.parse_args(argv), handlers


def test_register_returns_handler():
    args, handlers = _parse(["dashboard", "--port", "9000", "--open"])
    assert set(handlers) == {"dashboard"} and args.port == 9000 and args.open


def test_starts_on_loopback_and_prints_url(isolated, monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(kw))
    args, handlers = _parse(["dashboard", "--port", "9001"])
    out = io.StringIO()
    assert handlers["dashboard"](args, out, io.StringIO(), lambda: None) == 0
    assert calls["host"] == "127.0.0.1" and calls["port"] == 9001
    from jarvis.secrets import get_secret

    assert f"http://127.0.0.1:9001/#token={get_secret('dashboard_token')}" in out.getvalue()


def test_non_loopback_host_refused(isolated, monkeypatch):
    monkeypatch.setattr(cli_web, "load_web_settings", lambda: WebSettings(host="0.0.0.0"))
    args, handlers = _parse(["dashboard"])
    out = io.StringIO()
    assert handlers["dashboard"](args, out, io.StringIO(), lambda: None) == 2
    assert "Refusing" in out.getvalue()


def test_is_loopback():
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("192.168.1.5") and not is_loopback("example.com")
