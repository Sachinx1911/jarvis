"""Provider factory. Vendor adapters are imported lazily so the fake provider and the
test suite work without any vendor SDK being importable."""

from __future__ import annotations

from jarvis.config import Config
from jarvis.providers.base import ReasoningProvider


def make_provider(name: str, config: Config) -> ReasoningProvider:
    if name == "fake":
        from jarvis.providers.fake import FakeProvider

        return FakeProvider(models=config.models)
    if name == "anthropic":
        from jarvis.providers.claude import ClaudeProvider
        from jarvis.secrets import get_secret

        secret_name = config.providers.get("anthropic", {}).get("secret", "anthropic_api_key")
        return ClaudeProvider(get_secret(secret_name), config.models)
    raise ValueError(f"unknown provider: {name}")
