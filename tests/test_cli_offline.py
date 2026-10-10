"""Phase 0 done-when: the CLI greeting test passes offline with the fake provider."""

import io
import json
import sqlite3

from jarvis.cli import main


def test_init_creates_home(isolated):
    out = io.StringIO()
    assert main(["init"], out=out) == 0
    for rel in ("memory/facts", "profile", "data/tasks", "data/jarvis.db", "data/audit.jsonl"):
        assert (isolated / rel).exists(), rel


def test_greeting_with_fake_provider(isolated):
    out = io.StringIO()
    assert main(["chat", "--provider", "fake", "-m", "Hello Jarvis"], out=out) == 0
    assert "Good evening, sir." in out.getvalue()


def test_marathi_greeting_with_fake_provider(isolated):
    out = io.StringIO()
    assert main(["chat", "--provider", "fake", "-m", "नमस्कार Jarvis"], out=out) == 0
    assert "Good evening, sir." in out.getvalue()


def test_repl_until_exit(isolated):
    out = io.StringIO()
    inp = io.StringIO("hello\nwhat is 2+2\n/exit\nnever read\n")
    assert main(["chat", "--provider", "fake"], out=out, inp=inp) == 0
    text = out.getvalue()
    assert "Good evening, sir." in text
    assert "[fake] what is 2+2" in text
    assert "never read" not in text


def test_chat_is_logged_and_stored(isolated):
    main(["chat", "--provider", "fake", "-m", "hello"], out=io.StringIO())
    events = [json.loads(l)["event"] for l in (isolated / "data/audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["route_decision", "model_call"]
    conn = sqlite3.connect(isolated / "data/jarvis.db")
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert conn.execute("SELECT provider, route FROM model_usage").fetchone() == ("fake", "main_chat")


def test_anthropic_without_key_fails_cleanly(isolated):
    out = io.StringIO()
    assert main(["chat", "--provider", "anthropic", "-m", "hello"], out=out) == 1
    assert "Error (auth)" in out.getvalue()
    log = (isolated / "data/audit.jsonl").read_text(encoding="utf-8")
    assert "provider_error" in log


def test_secret_status_never_prints_values(isolated):
    from jarvis.secrets import set_secret

    set_secret("anthropic_api_key", "sk-ant-test-not-real")
    out = io.StringIO()
    assert main(["secret", "status"], out=out) == 0
    assert "anthropic_api_key: set" in out.getvalue()
    assert "sk-ant" not in out.getvalue()
