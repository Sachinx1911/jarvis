"""Phase 0 done-when: Jarvis replies "Good evening, sir." through the Claude adapter.

Costs a few cents. Runs only with JARVIS_LIVE=1 and a key in the real OS secret store:
    JARVIS_LIVE=1 pytest -m live
"""

import os
from datetime import datetime

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def real_key():
    if os.environ.get("JARVIS_LIVE") != "1":
        pytest.skip("set JARVIS_LIVE=1 to call the real API")
    from conftest import REAL_KEYRING

    key = REAL_KEYRING.get_password("jarvis", "anthropic_api_key")
    if not key:
        pytest.skip("no anthropic_api_key in the OS secret store")
    return key


def test_greeting_through_claude(real_key, isolated):
    from jarvis.config import load_config
    from jarvis.control.audit import AuditLog
    from jarvis.core.chat import ROUTE, ChatSession
    from jarvis.db import Store
    from jarvis.paths import default_paths
    from jarvis.providers.claude import ClaudeProvider
    from jarvis.routing.policy import decide

    config = load_config()
    decision = decide(config, ROUTE)
    paths = default_paths()
    session = ChatSession(
        config, ClaudeProvider(real_key, config.models), decision,
        Store(paths.db), AuditLog(paths.audit_log), now=lambda: datetime(2026, 10, 10, 19, 30),
    )
    reply = session.send("Hello Jarvis")
    assert "good evening" in reply.lower() and "sir" in reply.lower(), reply
