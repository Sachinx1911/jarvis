"""macOS Reminders and Calendar through EventKit (pyobjc). NEEDS A MAC.

PLAN.md section 13, item 3. On Windows and Linux the connector reports "needs macOS"
and registers no tools; pyobjc is not installed there. The Mac client below has NOT
been run yet (it was written on the Windows laptop): test it on the Mac before use.
On the Mac it needs `pyobjc-framework-EventKit` and a one-time permission prompt
(Reminders / Calendars) granted to Terminal.

Tiers: these tools were not classified by Sachin yet, so they follow the PLAN rule for
new connectors: T2 (ask first) and no agent access until he classifies them.
"""

from __future__ import annotations

import itertools
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

from jarvis.connectors.timeparse import TimeParseError, parse_iso
from jarvis.providers.base import ToolSpec
from jarvis.tools.registry import Tool

S = {"type": "string"}
UNCLASSIFIED_TIER = "T2"


class EventKitError(RuntimeError):
    pass


def is_supported() -> bool:
    return sys.platform == "darwin"


class EventKitClient(Protocol):
    def list_reminders(self) -> list[dict]: ...  # {"id", "title", "due"?: iso}

    def create_reminder(self, title: str, due: datetime | None) -> dict: ...

    def get_reminder(self, reminder_id: str) -> dict | None: ...

    def access(self) -> str: ...  # "granted" | "denied" | "not asked"


class FakeEventKitClient:
    def __init__(self, reminders: list[dict] | None = None, access: str = "granted"):
        self.reminders = {r["id"]: dict(r) for r in (reminders or [])}
        self._access = access
        self._ids = itertools.count(1)

    def list_reminders(self) -> list[dict]:
        return list(self.reminders.values())

    def create_reminder(self, title: str, due: datetime | None) -> dict:
        r = {"id": f"rem{next(self._ids)}", "title": title, "due": due.isoformat() if due else None}
        self.reminders[r["id"]] = r
        return dict(r)

    def get_reminder(self, reminder_id: str) -> dict | None:
        r = self.reminders.get(reminder_id)
        return dict(r) if r else None

    def access(self) -> str:
        return self._access


class MacEventKitClient:  # pragma: no cover - macOS only, not run on Windows
    """Reminders via EventKit. Untested until it runs on the Mac."""

    def __init__(self):
        if not is_supported():
            raise EventKitError("EventKit needs macOS")
        try:
            import EventKit  # pyobjc-framework-EventKit
        except ImportError as e:
            raise EventKitError("pyobjc-framework-EventKit is not installed") from e
        self.ek = EventKit
        self.store = EventKit.EKEventStore.alloc().init()

    def access(self) -> str:
        status = self.ek.EKEventStore.authorizationStatusForEntityType_(self.ek.EKEntityTypeReminder)
        # 0 not determined, 1 restricted, 2 denied, 3 full access (authorized), 4 write only
        return {0: "not asked", 3: "granted"}.get(int(status), "denied")

    def request_access(self, timeout: float = 60) -> bool:
        done, result = threading.Event(), {"ok": False}

        def handler(granted, error):
            result["ok"] = bool(granted)
            done.set()

        if hasattr(self.store, "requestFullAccessToRemindersWithCompletion_"):  # macOS 14+
            self.store.requestFullAccessToRemindersWithCompletion_(handler)
        else:
            self.store.requestAccessToEntityType_completion_(self.ek.EKEntityTypeReminder, handler)
        done.wait(timeout)
        return result["ok"]

    def _ensure_access(self) -> None:
        state = self.access()
        if state == "not asked" and self.request_access():
            return
        if state != "granted":
            raise EventKitError("no Reminders permission; allow Terminal in System Settings > Privacy > Reminders")

    def list_reminders(self) -> list[dict]:
        self._ensure_access()
        done, box = threading.Event(), {"items": []}
        pred = self.store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, None)

        def handler(items):
            box["items"] = list(items or [])
            done.set()

        self.store.fetchRemindersMatchingPredicate_completion_(pred, handler)
        if not done.wait(30):
            raise EventKitError("Reminders did not answer in time")
        return [self._reminder(r) for r in box["items"]]

    def _reminder(self, r) -> dict:
        comps = r.dueDateComponents()
        due = None
        if comps is not None and comps.year() < 10000:
            due = f"{comps.year():04d}-{comps.month():02d}-{comps.day():02d}"
            if comps.hour() < 25:
                due += f"T{comps.hour():02d}:{comps.minute():02d}"
        return {"id": str(r.calendarItemIdentifier()), "title": str(r.title() or ""), "due": due}

    def create_reminder(self, title: str, due: datetime | None) -> dict:
        from Foundation import NSDateComponents

        self._ensure_access()
        r = self.ek.EKReminder.reminderWithEventStore_(self.store)
        r.setTitle_(title)
        r.setCalendar_(self.store.defaultCalendarForNewReminders())
        if due is not None:
            comps = NSDateComponents.alloc().init()
            for setter, value in (("setYear_", due.year), ("setMonth_", due.month), ("setDay_", due.day),
                                  ("setHour_", due.hour), ("setMinute_", due.minute)):
                getattr(comps, setter)(value)
            r.setDueDateComponents_(comps)
        ok, error = self.store.saveReminder_commit_error_(r, True, None)
        if not ok:
            raise EventKitError(f"could not save the reminder: {error}")
        return self._reminder(r)

    def get_reminder(self, reminder_id: str) -> dict | None:
        item = self.store.calendarItemWithIdentifier_(reminder_id)
        return self._reminder(item) if item is not None else None


@dataclass
class EventKitTools:
    client_factory: Callable[[], EventKitClient | None]
    tz_name: str = "Asia/Kolkata"
    _client: EventKitClient | None = None
    _created: dict[str, str] = field(default_factory=dict)

    def client(self) -> EventKitClient | None:
        if self._client is None:
            self._client = self.client_factory()
        return self._client

    def reminders_list(self, args: dict) -> str:
        c = self.client()
        if c is None:
            return "Reminders are only available on the Mac."
        items = c.list_reminders()
        if not items:
            return "No open reminders."
        return "\n".join(f"- {r['title']}" + (f" (due {r['due']})" if r.get("due") else "") for r in items)

    def reminder_create(self, args: dict) -> str:
        c = self.client()
        if c is None:
            return "Reminders are only available on the Mac."
        try:
            due = parse_iso(args["due"], self.tz_name) if args.get("due") else None
        except TimeParseError as e:
            raise ValueError(str(e)) from e
        r = c.create_reminder(args["title"], due)
        self._created[args["title"] + "|" + (args.get("due") or "")] = r["id"]
        return f"Reminder created: {r['title']}" + (f" (due {r['due']})" if r.get("due") else "")

    def verify_reminder(self, args: dict) -> tuple[bool, str]:
        rid = self._created.get(args["title"] + "|" + (args.get("due") or ""))
        c = self.client()
        if not rid or c is None:
            return False, "no reminder id to check"
        r = c.get_reminder(rid)
        ok = bool(r) and r["title"] == args["title"]
        return ok, "reminder read back" if ok else "reminder not found when read back"

    def tools(self) -> list[Tool]:
        return [
            Tool(ToolSpec("reminders_list", "List open reminders in the Mac Reminders app.",
                          {"type": "object", "properties": {}, "required": []}),
                 UNCLASSIFIED_TIER, self.reminders_list),
            Tool(ToolSpec("reminder_create", "Create a reminder in the Mac Reminders app. due: ISO date-time from "
                          "parse_time (optional).", {"type": "object", "properties": {"title": S, "due": S},
                                                     "required": ["title"]}),
                 UNCLASSIFIED_TIER, self.reminder_create, verify=self.verify_reminder),
        ]


def default_client() -> EventKitClient | None:
    if not is_supported():
        return None
    try:
        return MacEventKitClient()
    except EventKitError:
        return None


def health(client_factory: Callable[[], EventKitClient | None] = default_client) -> tuple[bool, str]:
    if not is_supported() and client_factory is default_client:
        return False, "needs macOS (Reminders via EventKit); not available on this machine"
    client = client_factory()
    if client is None:
        return False, "pyobjc-framework-EventKit is not installed (pip install pyobjc-framework-EventKit)"
    access = client.access()
    if access != "granted":
        return False, f"Reminders permission {access}; allow Terminal in System Settings > Privacy > Reminders"
    return True, "Reminders access granted"
