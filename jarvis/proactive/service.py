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
from jarvis.proactive import integration as _integration  # noqa: F401 (registers the calendar section)
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
EXTRACT_NAME = "Memory extraction"
CLEANUP_NAME = "Memory cleanup"
REVIEW_NAME = "Nightly review"


def _memory_settings() -> dict[str, Any]:
    from jarvis.memory.upkeep_settings import load_memory_settings

    return load_memory_settings()


@dataclass
class Proactive:
    settings: ProactiveSettings = field(default_factory=load_settings)
    notifier: Any = None
    provider_override: str | None = None
    open_rt: Callable[[], Runtime] = open_runtime
    clock: Clock | None = None
    chat_factory: Callable[[Runtime, Approver], Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)   # e.g. {"web": WebClient(...)} for the brief
    memory_settings: dict[str, Any] = field(default_factory=_memory_settings)   # config/memory.yaml
    extractor_factory: Callable[[Runtime], Any] | None = None   # tests inject one on the fake provider

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
        from jarvis.proactive.integration import agent_task_executor
        return {"prompt": chat, "skill": chat, "agent": agent_task_executor, "brief": brief, "heartbeat": beat,
                "memory_extract": self._memory_extract, "memory_cleanup": self._memory_cleanup,
                "review": self._nightly_review}

    def _nightly_review(self, ctx: RunContext) -> str | None:
        from jarvis.proactive.review import nightly_review

        return nightly_review(ctx.rt.paths.home, ctx.rt.store.conn, ctx.rt.memory, ctx.now).summary

    def guard(self):
        """Global daily cap and runaway guard for unattended work (config: proactive unattended)."""
        from jarvis.proactive.guard import UnattendedGuard

        return UnattendedGuard.from_settings(self.settings.section("unattended"))

    # ---- memory upkeep (PLAN.md 6.3 rule 8, 6.6) ----

    def extractor(self, rt: Runtime):
        if self.extractor_factory is not None:
            return self.extractor_factory(rt)
        from jarvis.core.runtime import make_extractor

        return make_extractor(rt, self.provider_override)

    def _memory_extract(self, ctx: RunContext) -> str | None:
        from jarvis.memory.quiet import extract_quiet_sessions

        q = dict(self.memory_settings.get("quiet_extract") or {})
        run = extract_quiet_sessions(
            ctx.rt.store.conn, self.extractor(ctx.rt), ctx.now, quiet_minutes=float(q.get("quiet_minutes", 20)),
            max_age_hours=float(q.get("max_age_hours", 24)), max_sessions=int(q.get("max_sessions_per_run", 5)),
            max_failures=int(q.get("max_failures", 3)), audit=ctx.rt.audit)
        if run.skipped_reason or not run.outcomes:
            return None  # nothing to say: the run is recorded as "quiet"
        return run.summary()

    def _memory_cleanup(self, ctx: RunContext) -> str | None:
        from jarvis.memory.maintenance import MemoryCleanup

        settings = dict(self.memory_settings.get("cleanup") or {})
        report = MemoryCleanup(ctx.rt.memory, ctx.rt.paths.home, ctx.now.date(), ctx.rt.audit, settings).run()
        return report.summary() + (f"\nReport: {report.path}" if report.path else "")

    # ---- approvals queued by unattended runs ----

    def replay_registry(self, rt: Runtime, approver: Approver):
        """A fresh tool registry: the same tools a scheduled chat turn gets, with this approver."""
        return self.chat(rt, approver).tools

    def approve_pending(self, pid: int, source: str = "cli"):
        from jarvis.proactive.replay import approve_pending

        hours = float(self.settings.section("approvals").get("replay_max_age_hours", 24))
        rt = self.open_rt()
        try:
            return approve_pending(rt, pid, self.now(), self.replay_registry, self.notifier,
                                   timedelta(hours=hours), source, self.clock)
        finally:
            rt.close()

    def deny_pending(self, pid: int, source: str = "cli"):
        from jarvis.proactive.replay import deny_pending

        rt = self.open_rt()
        try:
            return deny_pending(rt, pid, self.now(), self.notifier, source)
        finally:
            rt.close()

    def runner(self) -> ScheduleRunner:
        stale = timedelta(hours=float(self.settings.section("schedules").get("stale_lock_hours", 6)))
        return ScheduleRunner(self.open_rt, self.executors(), self.notifier, self.clock, stale, self.default_budget,
                              guard=self.guard())

    def ensure_default_schedules(self) -> list[str]:
        """The brief and the heartbeat are ordinary schedules, so they can be paused like any other.
        Created once; after that Sachin's changes (pause, delete) are kept."""
        rt = self.open_rt()
        added = []
        try:
            store = ScheduleStore(rt.store.conn)
            now = self.now()
            b, h = self.settings.section("brief"), self.settings.section("heartbeat")
            q = dict(self.memory_settings.get("quiet_extract") or {})
            c = dict(self.memory_settings.get("cleanup") or {})
            r = dict(self.memory_settings.get("review") or {})
            every_q = int(q.get("every_minutes", 10))
            defaults = [
                (BRIEF_NAME, "brief", str(b.get("cron") or "0 8 * * *"), str(b.get("output") or self.default_output),
                 "every day at the brief time", b.get("enabled", True), self.grace_s),
                (HEARTBEAT_NAME, "heartbeat", f"*/{int(h.get('every_minutes', 30))} * * * *", "telegram",
                 f"every {int(h.get('every_minutes', 30))} minutes", h.get("enabled", True), 300),
                (EXTRACT_NAME, "memory_extract", f"*/{every_q} * * * *", str(q.get("output") or "file"),
                 f"every {every_q} minutes", q.get("enabled", True), 300),
                (CLEANUP_NAME, "memory_cleanup", str(c.get("cron") or "0 21 * * sun"),
                 str(c.get("output") or self.default_output), "every week (Sunday evening)", c.get("enabled", True),
                 self.grace_s),
                (REVIEW_NAME, "review", str(r.get("cron") or "30 22 * * *"), str(r.get("output") or "file"),
                 "every night", r.get("enabled", True), self.grace_s),
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

    # ---- event triggers (jarvis/proactive/triggers.py) ----

    @property
    def trigger_settings(self) -> dict[str, Any]:
        return self.settings.section("triggers")

    def trigger_engine(self):
        """Tests inject fakes through `extras`: "web" (WebClient), "tavily_key" (callable),
        "google_client" (callable returning a GoogleClient or None), "connectors_cfg" (dict)."""
        from jarvis.proactive.integration import agent_task_executor
        from jarvis.proactive.triggers import TriggerEngine

        web = self.extras.get("web")
        if web is None:
            from jarvis.tools.web import WebClient

            web = WebClient()
        key = self.extras.get("tavily_key")
        if key is None:
            from jarvis.secrets import get_secret

            key = lambda: get_secret("tavily_api_key")  # noqa: E731
        cfg = self.extras.get("connectors_cfg")
        if cfg is None:
            from jarvis.connectors.config import load_connectors_config

            cfg = load_connectors_config()
        google = self.extras.get("google_client")
        if google is None:
            from jarvis.connectors.registry import default_google_client

            google = default_google_client(cfg)
        return TriggerEngine(self.open_rt, self.trigger_settings, self.clock, chat=self.chat,  # type: ignore[arg-type]
                             agent_executor=agent_task_executor, notifier=self.notifier, web=web, tavily_key=key,
                             google=google, connectors_cfg=cfg, default_budget=self.default_budget,
                             guard=self.guard())

    def draft_trigger(self, text: str, defaults: dict[str, Any] | None = None):
        """Parse and validate; raises TriggerParseError (a question) or TriggerInvalid (a refusal)."""
        from jarvis.proactive.trigger_parse import parse_trigger

        defaults = {"output": self.default_output, **(defaults or {})}
        engine = self.trigger_engine()
        draft = parse_trigger(text, defaults)
        engine.apply_defaults(draft, every_given=bool(defaults.get("every_s")),
                              cooldown_given=defaults.get("cooldown_s") is not None)
        return engine.validate(draft)

    def save_trigger(self, draft, source: str = "cli"):
        from jarvis.proactive.triggers import TriggerStore

        self.trigger_engine().validate(draft)   # again: the folder or the store list may have changed
        rt = self.open_rt()
        try:
            t = TriggerStore(rt.store.conn).add(draft, self.now(), source)
            rt.audit.write("trigger_added", trigger_id=t.id, source_kind=t.source, action=t.action, created_by=source)
            return t
        finally:
            rt.close()

    def poll_triggers(self) -> list:
        if not self.trigger_settings.get("enabled", True):
            return []
        return self.trigger_engine().poll_due()

    def service(self) -> ScheduleService:
        every = int(self.settings.section("reminders").get("check_seconds", 30))
        sync = int(self.settings.section("schedules").get("sync_seconds", 60))
        jobs = [(self.fire_reminders, every, "_reminders")]
        if self.trigger_settings.get("enabled", True):
            jobs.append((self.poll_triggers, int(self.trigger_settings.get("poll_seconds", 60)), "_triggers"))
        sched = self.settings.section("schedules")
        quiet = tuple(sched.get("missed_alert_quiet_kinds") or ("heartbeat", "memory_extract"))
        return ScheduleService(self.runner(), self.settings.tz_name, sync, extra_jobs=jobs,
                               alert_missed=bool(sched.get("alert_missed", True)), quiet_kinds=quiet)
