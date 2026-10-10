"""Secrets in the OS secret store via keyring.

macOS: Keychain. Windows: Credential Manager. Never in files, never in logs.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICE = "jarvis"
KNOWN_SECRETS = ("anthropic_api_key", "tavily_api_key", "telegram_bot_token", "dashboard_token")


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError:
        return None


def set_secret(name: str, value: str) -> None:
    if not value:
        raise ValueError("empty secret")
    keyring.set_password(SERVICE, name, value)


def delete_secret(name: str) -> None:
    keyring.delete_password(SERVICE, name)
