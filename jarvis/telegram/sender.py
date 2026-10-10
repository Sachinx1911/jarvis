"""Send a Telegram message with one HTTPS call (standard library only).

Used for notifications from the scheduler, reminders and the CLI, whether or not the
bot's long-polling loop is running. The bot token is part of the API URL, so the URL is
never logged or put into an error message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

API = "https://api.telegram.org"
TIMEOUT = 20
MAX_TEXT = 4000  # Telegram's limit is 4096 characters per message

# (url, json body) -> (status, response bytes)
Transport = Callable[[str, bytes], tuple[int, bytes]]


class TelegramSendError(Exception):
    pass


def _default_transport(url: str, body: bytes) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (fixed https host)
            return resp.status, resp.read(100_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(100_000) if e.fp else b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TelegramSendError(f"network error: {type(e).__name__}") from None


def chunks(text: str, size: int = MAX_TEXT) -> list[str]:
    """Split on line breaks where possible so long briefs arrive in readable parts."""
    text = text or "(empty)"
    out: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else size
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    out.append(text)
    return out


class TelegramSender:
    def __init__(self, token: str, chat_id: int, transport: Transport | None = None):
        if not token:
            raise ValueError("no Telegram bot token")
        self._token = token
        self.chat_id = chat_id
        self.transport = transport or _default_transport

    def __repr__(self) -> str:  # never show the token
        return f"TelegramSender(chat_id={self.chat_id})"

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        status, raw = self.transport(f"{API}/bot{self._token}/{method}", json.dumps(payload).encode())
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            data = {}
        if status >= 400 or not data.get("ok", False):
            raise TelegramSendError(f"Telegram {method} failed: HTTP {status} {data.get('description', '')}".strip())
        return data

    def send(self, text: str) -> None:
        for part in chunks(text):
            self.call("sendMessage", {"chat_id": self.chat_id, "text": part,
                                     "link_preview_options": {"is_disabled": True}})
