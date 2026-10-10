"""Phase 0 done-when: Jarvis replies "Good evening, sir." through a real Claude adapter.

Opt-in only: JARVIS_LIVE=1 pytest -m live
- Subscription test: uses the logged-in Claude Code CLI (counts against the plan's usage limits).
- API test: needs anthropic_api_key in the real OS secret store (costs a few cents).
"""

import os
import shutil
from datetime import datetime

import pytest

pytestmark = pytest.mark.live


def _require_live():
    if os.environ.get("JARVIS_LIVE") != "1":
        pytest.skip("set JARVIS_LIVE=1 to call a real provider")


@pytest.fixture
def real_key():
    _require_live()
    from conftest import REAL_KEYRING

    key = REAL_KEYRING.get_password("jarvis", "anthropic_api_key")
    if not key:
        pytest.skip("no anthropic_api_key in the OS secret store")
    return key


def _greet(provider_name, provider):
    from jarvis.config import load_config
    from jarvis.control.audit import AuditLog
    from jarvis.core.chat import ROUTE, ChatSession
    from jarvis.db import Store
    from jarvis.paths import default_paths
    from jarvis.routing.policy import RouteDecision

    config = load_config()
    decision = RouteDecision(ROUTE, provider_name, "claude-opus-5-5", "low", "live test")
    paths = default_paths()
    session = ChatSession(
        config, provider, decision,
        Store(paths.db), AuditLog(paths.audit_log), now=lambda: datetime(2026, 10, 10, 19, 30),
    )
    return session.send("Hello Jarvis")


def test_greeting_through_subscription_cli(isolated):
    _require_live()
    if not shutil.which("claude"):
        pytest.skip("Claude Code CLI not installed")
    from jarvis.config import load_config
    from jarvis.providers.claude_code import ClaudeCodeProvider

    reply = _greet("claude_code", ClaudeCodeProvider(load_config().models))
    assert "good evening" in reply.lower() and "sir" in reply.lower(), reply


def test_greeting_through_api(real_key, isolated):
    from jarvis.config import load_config
    from jarvis.providers.claude import ClaudeProvider

    reply = _greet("anthropic", ClaudeProvider(real_key, load_config().models))
    assert "good evening" in reply.lower() and "sir" in reply.lower(), reply
