"""`jarvis connectors status --live` asks for the live checks; without it nothing live runs."""

import io

import jarvis.connectors.registry as registry
from jarvis.cli import main as cli_main


def _run(monkeypatch, argv):
    seen = {}

    def fake_health(deps, live=False, notes_live=False):
        seen.update(live=live, notes_live=notes_live)
        return [("demo", True, "fine")]

    monkeypatch.setattr(registry, "connector_health", fake_health)
    out = io.StringIO()
    assert cli_main(argv, out=out) == 0
    return seen, out.getvalue()


def test_status_is_offline_by_default(monkeypatch):
    seen, text = _run(monkeypatch, ["connectors", "status"])
    assert seen == {"live": False, "notes_live": False} and "demo: OK - fine" in text


def test_live_flag_runs_live_checks(monkeypatch):
    seen, _ = _run(monkeypatch, ["connectors", "status", "--live"])
    assert seen == {"live": True, "notes_live": True}
