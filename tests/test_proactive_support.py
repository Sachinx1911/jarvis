"""Shared fakes for the Phase 4 tests (no tests in here). Offline: fake provider, fake clock,
fake notifier, fake Telegram objects."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from jarvis.core.chat import ChatSession
from jarvis.proactive.service import Proactive
from jarvis.proactive.settings import ProactiveSettings
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

IST = ZoneInfo("Asia/Kolkata")
MAIN = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")


def at(*args) -> datetime:
    return datetime(*args, tzinfo=IST)


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeNotifier:
    name = "fake"

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, text: str, title: str = "Jarvis") -> str:
        if self.fail:
            raise RuntimeError("offline")
        self.sent.append((title, text))
        return self.name


def settings(**over) -> ProactiveSettings:
    raw = {"timezone": "Asia/Kolkata", "quiet_hours": {"start": "22:30", "end": "07:00"},
           "schedules": {"misfire_grace_minutes": 60, "default_output": "telegram",
                         "default_budget": {"max_model_calls": 12}},
           "heartbeat": {"enabled": True, "every_minutes": 30, "repeat_after_hours": 6},
           "brief": {"enabled": True, "cron": "0 8 * * *", "place": "", "output": "telegram"},
           "telegram": {"allowed_user_id": 1111, "approval_timeout_seconds": 5}}
    raw.update(over)
    return ProactiveSettings(raw)


class ScriptedChats:
    """chat_factory that builds a real ChatSession on the fake provider with a script per session."""

    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.providers: list[FakeProvider] = []
        self.approvers = []

    def __call__(self, rt, approver):
        provider = FakeProvider(script=self.scripts.pop(0) if self.scripts else [])
        self.providers.append(provider)
        self.approvers.append(approver)
        return ChatSession(rt.config, provider, MAIN, rt.store, rt.audit, home=rt.paths.home, memory=rt.memory,
                           approver=approver, web=WebClient(transport=lambda *a: (404, b""), check_url=lambda u: None),
                           system=SystemTools(apps={}, runner=lambda a: None, opener=lambda u: True))

    @property
    def calls(self) -> int:
        return sum(len(p.requests) for p in self.providers)


def proactive(now: datetime, chats: ScriptedChats | None = None, notifier=None, **over) -> Proactive:
    return Proactive(settings(**over), notifier=notifier, provider_override="fake", clock=Clock(now),
                     chat_factory=chats or ScriptedChats())


# ---- Telegram fakes ----

class FakeMessage:
    def __init__(self, text: str | None = None):
        self.text = text
        self.replies: list[tuple[str, object]] = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers: list = []
        self.edits: list[str] = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)


class FakeBot:
    def __init__(self):
        self.sent: list[dict] = []
        self.edited: list[dict] = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, **kw):
        self.edited.append(kw)

    async def send_chat_action(self, **kw):
        pass


def update(user_id: int, text: str | None = None, data: str | None = None):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username="someone"),
                           effective_message=FakeMessage(text), callback_query=FakeQuery(data) if data else None)


def button_data(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]
