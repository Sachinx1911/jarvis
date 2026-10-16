"""Joins Phase 4 (proactive) with Phases 3 and 5: the brief's calendar section comes from
the Google connector, and agent schedules run through the Phase 3 team runner.

Email stays a placeholder in the brief: whether sender and subject are P1 or P2 is still
Sachin's open decision, and the brief goes out over Telegram.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable

from jarvis.proactive.brief import BriefContext, register_section


class CalendarSection:
    key, title, order = "calendar", "Calendar today", 20

    def __init__(self, client_factory: Callable[[], object | None] | None = None):
        self.client_factory = client_factory

    def _client(self):
        if self.client_factory is not None:
            return self.client_factory()
        from jarvis.connectors.config import load_connectors_config
        from jarvis.connectors.registry import default_google_client

        return default_google_client(load_connectors_config())()

    def render(self, ctx: BriefContext) -> str | None:
        client = self._client()
        if client is None:
            return "Google Calendar is not connected (jarvis google auth)."
        start = datetime.combine(ctx.now.date(), time.min, tzinfo=ctx.now.tzinfo)
        events = client.list_events("primary", start, start + timedelta(days=1), max_results=15)  # type: ignore[attr-defined]
        if not events:
            return "No events today."
        lines = []
        for e in events:
            when = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or ""
            hhmm = when[11:16] if len(when) >= 16 else "all day"
            lines.append(f"- {hhmm} {e.get('summary') or '(no title)'}")  # titles and times are P1
        return "\n".join(lines)


def _default_runner(rt):
    from jarvis.core.runtime import make_task_runner

    return make_task_runner(rt, approver=None)


# Replaceable in tests, so no test ever reaches a real model.
RUNNER_FACTORY: Callable = _default_runner


def agent_task_executor(ctx) -> str:
    """Agent schedules: create a task and run it with the Phase 3 team, unattended.

    No approver is given, so anything above T1 is refused (PLAN.md 10.3: unattended runs may
    only do T0/T1); the receipt records what was refused.
    """
    from jarvis.core.runtime import task_store

    s = ctx.schedule
    tasks = task_store(ctx.rt)
    task = tasks.create(goal=s.input or s.name, title=s.name, budget=s.budget or None,
                        workspace=getattr(s, "workspace", "personal") or "personal")
    tasks.update(task.id, owner=s.target)
    tasks.event(task.id, "scheduled", {"schedule_id": s.id, "run_id": ctx.run_id, "agent": s.target})
    done = RUNNER_FACTORY(ctx.rt).run(task.id)
    receipt = ctx.rt.paths.data / "tasks" / task.id / "receipt.md"
    return f"Task {task.id} ({s.name}): {done.state}. Receipt: {receipt}"


register_section(CalendarSection())

# India sections: public alerts, NAVs, bills/documents due (counts by default), Marathi headlines.
from jarvis.india.brief_sections import register_india_sections  # noqa: E402

register_india_sections()

# Possible memory conflicts (counts only), from the nightly review work.
from jarvis.proactive.review import MemoryConflictsSection  # noqa: E402

register_section(MemoryConflictsSection())
