import pytest

from jarvis.config import Config, load_config
from jarvis.routing.policy import RoutingError, decide


def _config(**routing) -> Config:
    base = load_config()
    return Config(base.providers, base.models, {**base.routing, **routing})


def test_default_main_chat_is_opus():
    d = decide(load_config(), "main_chat")
    assert (d.provider, d.model, d.effort) == ("anthropic", "claude-opus-5-5", "medium")


def test_fake_override_always_allowed():
    assert decide(load_config(), "main_chat", "fake").provider == "fake"


def test_unapproved_provider_is_never_used():
    with pytest.raises(RoutingError, match="not approved"):
        decide(_config(approved_providers=[]), "main_chat")


def test_cloud_switch_off_blocks_cloud():
    with pytest.raises(RoutingError, match="cloud not allowed"):
        decide(_config(cloud_allowed=False), "main_chat")


def test_missing_capability_skips_candidate():
    cfg = _config(routes={"r": {"candidates": [
        {"provider": "anthropic", "model": "unknown-model"},
        {"provider": "anthropic", "model": "claude-haiku-5-5", "effort": "low"},
    ], "needs": ["tools"]}})
    d = decide(cfg, "r")
    assert d.model == "claude-haiku-5-5"
    assert "unknown-model: missing tools" in d.reason


def test_unknown_route():
    with pytest.raises(RoutingError):
        decide(load_config(), "nope")
