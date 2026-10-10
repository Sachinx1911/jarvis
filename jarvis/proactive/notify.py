"""Where proactive messages go: Telegram when configured, else a desktop notification,
else the console. A channel that fails passes the message to the next one, so a
reminder is never lost just because the network is down.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol, TextIO

from jarvis.control.audit import AuditLog
from jarvis.proactive.settings import ProactiveSettings
from jarvis.secrets import get_secret


class Notifier(Protocol):
    name: str

    def send(self, text: str, title: str = "Jarvis") -> None: ...


@dataclass
class ConsoleNotifier:
    out: TextIO | None = None
    name: str = "console"

    def send(self, text: str, title: str = "Jarvis") -> None:
        print(f"[{title}] {text}", file=self.out or sys.stdout, flush=True)


class DesktopNotifier:
    """OS notification through the existing system tool (Windows balloon / macOS osascript)."""

    name = "desktop"

    def __init__(self, system=None):
        from jarvis.tools.system import IS_MAC, IS_WINDOWS, SystemTools

        if not (IS_MAC or IS_WINDOWS):
            raise RuntimeError("desktop notifications need Windows or macOS")
        self.system = system or SystemTools()

    def send(self, text: str, title: str = "Jarvis") -> None:
        # Notification bubbles are small; the full text goes to Telegram or the console.
        short = text if len(text) <= 240 else text[:237] + "..."
        result = self.system.notify({"title": title, "message": short})
        if not result.startswith("Notification shown"):
            raise RuntimeError(result)


class TelegramNotifier:
    name = "telegram"

    def __init__(self, sender):
        self.sender = sender

    def send(self, text: str, title: str = "Jarvis") -> None:
        self.sender.send(text if title in ("", "Jarvis") else f"{title}\n{text}")


class FallbackNotifier:
    """Tries each channel in order; the first that works wins."""

    def __init__(self, channels: list[Notifier], audit: AuditLog | None = None):
        if not channels:
            raise ValueError("no notification channel")
        self.channels = channels
        self.audit = audit

    @property
    def name(self) -> str:
        return self.channels[0].name

    def send(self, text: str, title: str = "Jarvis") -> str:
        errors = []
        for ch in self.channels:
            try:
                ch.send(text, title)
                if self.audit:
                    self.audit.write("notify", channel=ch.name, title=title, chars=len(text),
                                     failed=[e.split(":")[0] for e in errors])
                return ch.name
            except Exception as e:  # noqa: BLE001 - any channel failure falls through to the next
                errors.append(f"{ch.name}: {type(e).__name__}: {e}")
        if self.audit:
            self.audit.write("notify_failed", title=title, errors=errors)
        raise RuntimeError("every notification channel failed: " + "; ".join(errors))


def telegram_sender(settings: ProactiveSettings):
    """A TelegramSender when a token and the allowed user ID are set, else None."""
    from jarvis.telegram.sender import TelegramSender

    token = get_secret(settings.telegram_secret)
    user_id = settings.telegram_user_id
    if not token or not user_id:
        return None
    return TelegramSender(token, user_id)  # a private chat's id equals the user id


def make_notifier(settings: ProactiveSettings, audit: AuditLog | None = None, out: TextIO | None = None,
                  telegram=None, desktop: bool = True) -> FallbackNotifier:
    channels: list[Notifier] = []
    sender = telegram if telegram is not None else telegram_sender(settings)
    if sender is not None:
        channels.append(TelegramNotifier(sender))
    if desktop:
        try:
            channels.append(DesktopNotifier())
        except RuntimeError:
            pass
    channels.append(ConsoleNotifier(out))
    return FallbackNotifier(channels, audit)
