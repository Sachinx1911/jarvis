"""Daily brief (PLAN.md 12): weather, reminders, goals, open tasks, today's schedules,
and (from Phase 5) calendar and email.

Built from sections without a model: facts come from stores and APIs, so the brief
cannot invent anything, costs nothing, and works with cloud AI switched off.

Connectors add sections later with `register_section(...)`:

    class CalendarToday:
        key = "calendar"; title = "Calendar"; order = 20
        def render(self, ctx: BriefContext) -> str | None: ...
    register_section(CalendarToday())   # replaces the Phase 4 placeholder with the same key

A section that raises is shown as "unavailable" and logged; the rest of the brief still
arrives. A section that returns None is left out.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from jarvis.control.audit import AuditLog


@dataclass
class BriefContext:
    now: datetime
    home: Path
    store: Any                          # jarvis.db.Store
    settings: Any                       # ProactiveSettings
    extras: dict[str, Any] = field(default_factory=dict)  # e.g. a WebClient for tests

    @property
    def conn(self) -> sqlite3.Connection:
        return self.store.conn


@runtime_checkable
class BriefSection(Protocol):
    key: str        # unique; a later registration with the same key replaces the earlier one
    title: str
    order: int      # lower comes first

    def render(self, ctx: BriefContext) -> str | None: ...


_REGISTRY: dict[str, BriefSection] = {}


def register_section(section: BriefSection) -> None:
    _REGISTRY[section.key] = section


def registered_sections() -> list[BriefSection]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.order, s.key))


# ---------------------------------------------------------------- built-in sections


class WeatherSection:
    key, title, order = "weather", "Weather", 10

    def render(self, ctx: BriefContext) -> str | None:
        from jarvis.tools.web import WebClient, format_weather

        place = str(ctx.settings.section("brief").get("place") or "").strip()
        if not place:
            return "No default place set (config/local.yaml: proactive_file.brief.place)."
        web = ctx.extras.get("web") or WebClient()
        lines = format_weather(web.weather(place, days=1)).splitlines()
        return "\n".join(lines[1:]) or lines[0]  # drop the header line; the section has a title


class PlaceholderSection:
    """Until the Phase 5 connectors register the real section under the same key."""

    def __init__(self, key: str, title: str, order: int, phase: str):
        self.key, self.title, self.order, self.phase = key, title, order, phase

    def render(self, ctx: BriefContext) -> str | None:
        return f"Not connected yet ({self.phase})."


class RemindersSection:
    key, title, order = "reminders", "Reminders today", 30

    def render(self, ctx: BriefContext) -> str | None:
        from jarvis.proactive.reminders import ReminderStore

        start = ctx.now.replace(hour=0, minute=0, second=0, microsecond=0)
        items = ReminderStore(ctx.conn).upcoming(ctx.now, start + timedelta(days=1))
        if not items:
            return "None."
        return "\n".join(f"- {r.due_at:%H:%M} {r.text}" for r in items)


class GoalsSection:
    """Goals from <home>/profile/goals.md (bullet lines). Weekly/monthly tracking comes later."""
    key, title, order = "goals", "Goals", 40

    def render(self, ctx: BriefContext) -> str | None:
        path = ctx.home / "profile" / "goals.md"
        if not path.exists():
            return None
        goals = [l.strip()[2:] for l in path.read_text(encoding="utf-8").splitlines()
                 if l.strip().startswith(("- ", "* ")) and "[x]" not in l.lower()]
        return "\n".join(f"- {g}" for g in goals[:7]) or None


class TasksSection:
    key, title, order = "tasks", "Open tasks", 50

    def render(self, ctx: BriefContext) -> str | None:
        from jarvis.tasks.store import TaskStore

        tasks = TaskStore(ctx.store, ctx.home / "data" / "tasks").list()
        if not tasks:
            return "None."
        lines = [f"- {t.id} [{t.state}] {t.title}" + (f" (due {t.deadline})" if t.deadline else "") for t in tasks[:8]]
        if len(tasks) > 8:
            lines.append(f"... and {len(tasks) - 8} more (/tasks)")
        return "\n".join(lines)


class SchedulesSection:
    key, title, order = "schedules", "Scheduled today", 60

    def render(self, ctx: BriefContext) -> str | None:
        from jarvis.proactive.scheduler import ScheduleStore

        end = ctx.now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        lines = []
        for s in ScheduleStore(ctx.conn).list():
            if not s.enabled or s.kind in ("brief", "heartbeat", "memory_extract"):
                continue
            nxt = s.next_after(ctx.now)
            if nxt and nxt < end:
                lines.append(f"- {nxt:%H:%M} {s.name} ({s.id})")
        return "\n".join(lines) or "Nothing else today."


def _install_defaults() -> None:
    for sec in (WeatherSection(), PlaceholderSection("calendar", "Calendar", 20, "Phase 5"), RemindersSection(),
                GoalsSection(), TasksSection(), SchedulesSection(),
                PlaceholderSection("email", "Important email", 70, "Phase 5")):
        _REGISTRY.setdefault(sec.key, sec)


_install_defaults()


# ---------------------------------------------------------------- building


@dataclass
class Brief:
    text: str
    failed: list[str]


def build_brief(ctx: BriefContext, sections: list[BriefSection] | None = None,
                audit: AuditLog | None = None) -> Brief:
    parts = [f"Good morning, sir. {ctx.now:%A, %d %B %Y}."]
    failed = []
    for sec in sections if sections is not None else registered_sections():
        try:
            body = sec.render(ctx)
        except Exception as e:  # noqa: BLE001 - one broken section must not cost the whole brief
            failed.append(sec.key)
            if audit:
                audit.write("brief_section_failed", section=sec.key, error=f"{type(e).__name__}: {e}")
            body = "Unavailable right now."
        if body:
            parts.append(f"{sec.title}\n{body}")
    if audit:
        audit.write("brief_built", sections=len(parts) - 1, failed=failed)
    return Brief("\n\n".join(parts), failed)
