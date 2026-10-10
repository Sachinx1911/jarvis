"""Wires schedules, heartbeat, brief, reminders and the notifier to the Jarvis runtime.

One object (`Proactive`) that the CLI, the daemon and the Telegram bot share, so they all
use the same settings, clock, routes and executors. Every operation opens its own
Runtime (and so its own SQLite connection) because it may run in a scheduler thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from jarvis.control.approvals import Approver
from jarvis.core.runtime import Runtime, make_chat, open_runtime
from jarvis.proactive import heartbeat as heartbeat_mod
from jarvis.proactive import schedule_parse
from jarvis.proactive.brief import Brief, BriefContext, build_brief
from jarvis.proactive.cloud import apply_cloud_override
from jarvis.proactive.heartbeat import Heartbeat, HeartbeatResult
from jarvis.proactive.reminders import ReminderStore
from jarvis.proactive.schedule_parse import ScheduleDraft, ScheduleParser
from jarvis.proactive.scheduler import (
    Executor, RunContext, ScheduleRunner, ScheduleService, ScheduleStore, chat_executor, queue_agent_task,
)
from jarvis.proactive.settings import Clock, ProactiveSettings, decide_route, load_settings
from jarvis.providers import make_provider
from jarvis.routing.policy import RoutingError

HEARTBEAT_NAME = "Heartbeat"
BRIEF_NAME = "Daily brief"


@dataclass
class Proactive:
    settings: ProactiveSettings = field(default_factory=load_settings)
    notifier: Any = None
    provider_override: str | None = None
    open_rt: Callable[[], Runtime] = open_runtime
    clock: Clock | None = None
    chat_factory: Callable[[Runtime, Approver], Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)   # e.g. {"web": WebClient(...)} for the brief

    def __post_init__(self):
        if self.clock is None:
            self.clock = self.settings.clock()

    def now(self):
        return self.clock()  # type: ignore[misc]

    # ---- settings ----

    @property
    def grace_s(self) -> int:
        return int(float(self.settings.section("schedules").get("misfire_grace_minutes", 60)) * 60)

    @property
    def default_output(self) -> str:
        return str(self.settings.section("schedules").get("default_output", "telegram"))

    @property
    def default_budget(self) -> dict[str, Any]:
        return dict(self.settings.section("schedules").get("default_budget") or {})

    # ---- models (only through the provider layer) ----

    def provider_for(self, rt: Runtime, route: str):
        """(provider, decision), or (None, None) when no route is allowed (e.g. cloud off)."""
        try:
            decision = decide_route(rt.config, self.settings, route, self.provider_override)
        except RoutingError as e:
            rt.audit.write("routing_error", route=route, detail=str(e))
            return None, None
        return make_provider(decision.provider, rt.config), decision

    def chat(self, rt: Runtime, approver: Approver):
        if self.chat_factory is not None:
            return self.chat_factory(rt, approver)
        rt.config = apply_cloud_override(rt.config)
        return make_chat(rt, self.provider_override, approver)

    # ---- pieces ----

    def parser(self, rt: Runtime, use_model: bool = True) -> ScheduleParser:
        provider, decision = self.provider_for(rt, schedule_parse.ROUTE) if use_model else (None, None)
        return ScheduleParser(self.settings.tz_name, provider, decision, rt.audit, rt.store)

    def draft(self, text: str, defaults: dict[str, Any] | None = None, use_model: bool = True) -> ScheduleDraft:
        defaults = {"output": self.default_output, **(defaults or {})}
        rt = self.open_rt()
        try:
            return self.parser(rt, use_model).parse(text, defaults)
        finally:
            rt.close()

    def save(self, draft: ScheduleDraft, source: str = "cli"):
        rt = self.open_rt()
        try:
            grace = 300 if draft.kind == "heartbeat" else self.grace_s
            s = ScheduleStore(rt.store.conn).add(draft, self.now(), grace, source)
            rt.audit.write("schedule_added", schedule_id=s.id, cron=s.cron, kind=s.kind, source=source)
            return s
        finally:
            rt.close()

    def brief(self, rt: Runtime) -> Brief:
        ctx = BriefContext(self.now(), rt.paths.home, rt.store, self.settings, dict(self.extras))
        return build_brief(ctx, audit=rt.audit)

    def heartbeat(self, rt: Runtime) -> Heartbeat:
        provider, decision = self.provider_for(rt, heartbeat_mod.ROUTE)
        return Heartbeat(rt.paths.home, self.settings, rt.store.conn, rt.audit, provider, decision, rt.store)

    def heartbeat_once(self) -> HeartbeatResult:
        rt = self.open_rt()
        try:
            return self.heartbeat(rt).run(self.now())
        finally:
            rt.close()

    def brief_text(self) -> str:
        rt = self.open_rt()
        try:
            return self.brief(rt).text
        finally:
            rt.close()

    # ---- schedules ----

    def executors(self) -> dict[str, Executor]:
        def brief(ctx: RunContext) -> str | None:
            return self.brief(ctx.rt).text

        def beat(ctx: RunContext) -> str | None:
            result = self.heartbeat(ctx.rt).run(ctx.now)
            return result.message if result.spoke else None

        chat = chat_executor(self.chat)
        return {"prompt": chat, "skill": chat, "agent": queue_agent_task, "brief": brief, "heartbeat": beat}

    def runner(self) -> ScheduleRunner:
        stale = timedelta(hours=float(self.settings.section("schedules").get("stale_lock_hours", 6)))
        return ScheduleRunner(self.open_rt, self.executors(), self.notifier, self.clock, stale, self.default_budget)

    def ensure_default_schedules(self) -> list[str]:
        """The brief and the heartbeat are ordinary schedules, so they can be paused like any other.
        Created once; after that Sachin's changes (pause, delete) are kept."""
        rt = self.open_rt()
        added = []
        try:
            store = ScheduleStore(rt.store.conn)
            now = self.now()
            b, h = self.settings.section("brief"), self.settings.section("heartbeat")
            defaults = [
                (BRIEF_NAME, "brief", str(b.get("cron") or "0 8 * * *"), str(b.get("output") or self.default_output),
                 "every day at the brief time", b.get("enabled", True), self.grace_s),
                (HEARTBEAT_NAME, "heartbeat", f"*/{int(h.get('every_minutes', 30))} * * * *", "telegram",
                 f"every {int(h.get('every_minutes', 30))} minutes", h.get("enabled", True), 300),
            ]
            marker = rt.paths.data / "proactive_defaults_created"
            created_before = set(marker.read_text(encoding="utf-8").split()) if marker.exists() else set()
            for name, kind, cron, output, desc, enabled, grace in defaults:
                if not enabled or kind in created_before or store.find(name):
                    continue
                draft = ScheduleDraft(name=name, kind=kind, input="", cron=schedule_parse.normalize_cron(cron),
                                      timezone=self.settings.tz_name, description=desc, output=output,
                                      source="default")
                s = store.add(draft, now, grace, source="default")
                added.append(s.id)
                created_before.add(kind)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(" ".join(sorted(created_before)), encoding="utf-8")
        finally:
            rt.close()
        return added

    # ---- reminders ----

    def fire_reminders(self) -> int:
        if self.notifier is None:
            return 0
        rt = self.open_rt()
        try:
            return len(ReminderStore(rt.store.conn, rt.audit).fire_due(self.now(), self.notifier))
        finally:
            rt.close()

    def service(self) -> ScheduleService:
        every = int(self.settings.section("reminders").get("check_seconds", 30))
        sync = int(self.settings.section("schedules").get("sync_seconds", 60))
        return ScheduleService(self.runner(), self.settings.tz_name, sync,
                               extra_jobs=[(self.fire_reminders, every, "_reminders")])
