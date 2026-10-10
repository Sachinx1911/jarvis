"""What the Telegram bot does, without any Telegram library code (so it is testable offline).

Thread rules: the chat session and its Runtime are created and used only in the bot's
single chat thread (SQLite connections must stay in their thread). Commands open their
own short-lived Runtime. /stop and /resume touch only the stop file and the audit log,
never a model or the database, so they work even while a chat turn is busy.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from jarvis.control.approvals import Approver
from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.paths import default_paths
from jarvis.proactive.cloud import cloud_override, set_cloud_override
from jarvis.proactive.reminders import ReminderStore, parse_reminder
from jarvis.proactive.schedule_parse import ScheduleDraft, ScheduleParseError
from jarvis.proactive.scheduler import PendingApprovals, ScheduleStore
from jarvis.proactive.service import Proactive
from jarvis.providers.base import ProviderError
from jarvis.routing.policy import RoutingError
from jarvis.telegram.approvals import ApprovalBroker

DRAFT_TTL_SECONDS = 600

HELP = """Jarvis commands:
/stop [reason] - emergency stop (no model or tool runs)
/resume - release the emergency stop
/tasks - open tasks;  /task <id> - one task
/pause <task id>, /cancel <task id>
/schedules - list schedules
/schedule <text> - new schedule, e.g. /schedule every Monday at 9 project summary
/schedule_pause <id>, /schedule_resume <id>, /schedule_run <id>, /schedule_delete <id>
/approvals - actions from unattended runs that wait for you (Approve/Deny buttons)
/approve <id> - run that exact queued action once;  /deny <id>;  /dismiss <id>
/remind <text> - e.g. /remind in 10 minutes call back
/reminders - pending reminders
/brief - today's brief now
/cloud off|on|status - switch cloud AI off for this machine (on = back to config)
/new - start a fresh conversation (saves what Jarvis learned)
Anything else is a chat message to Jarvis."""


@dataclass
class _Draft:
    draft: ScheduleDraft
    created: float


class BotCore:
    def __init__(self, proactive: Proactive, allowed_user_id: int, audit: AuditLog | None = None,
                 broker: ApprovalBroker | None = None):
        if not allowed_user_id:
            raise ValueError("no allowed Telegram user id configured; the bot will not start")
        self.p = proactive
        self.allowed_user_id = int(allowed_user_id)
        paths = default_paths()
        self.data_dir = paths.data
        self.audit = audit or AuditLog(paths.audit_log)
        self.broker = broker or ApprovalBroker()
        self.stop = StopSwitch(self.data_dir)
        self._drafts: dict[str, _Draft] = {}
        self._drafts_lock = threading.Lock()
        self._rt = None       # chat thread only
        self._session = None  # chat thread only

    # ---- who may talk ----

    def is_allowed(self, user_id: int | None) -> bool:
        return user_id is not None and int(user_id) == self.allowed_user_id

    def rejected(self, user_id: int | None, username: str | None, kind: str) -> None:
        # Message text is not logged: it comes from a stranger and may be anything.
        self.audit.write("telegram_rejected", user_id=user_id, username=username, update=kind)

    # ---- emergency stop: no model, no database ----

    def cmd_stop(self, reason: str = "") -> str:
        self.stop.engage(f"telegram /stop {reason}".strip())
        denied = self.broker.deny_all()
        self.audit.write("emergency_stop", source="telegram", reason=reason, approvals_denied=denied)
        return "Emergency stop ON. No model or tool will run. /resume to release."

    def cmd_resume(self) -> str:
        self.stop.release()
        self.audit.write("emergency_stop_released", source="telegram")
        return "Emergency stop OFF."

    # ---- cloud switch ----

    def cmd_cloud(self, arg: str) -> str:
        arg = arg.strip().lower()
        if arg in ("off", "on"):
            set_cloud_override(arg == "on", source="telegram")
            self.audit.write("cloud_override", value=arg, source="telegram")
            self._drop_session()  # the next message routes again under the new setting
        state = cloud_override()
        if state is None:
            return "Cloud AI: as configured (routing.yaml). /cloud off to switch it off on this machine."
        return "Cloud AI: OFF on this machine. Jarvis uses only local models (if any). /cloud on to undo."

    # ---- tasks ----

    def _with_rt(self, fn: Callable[[Any], str]) -> str:
        rt = self.p.open_rt()
        try:
            return fn(rt)
        finally:
            rt.close()

    def cmd_tasks(self) -> str:
        from jarvis.tasks.store import TaskStore

        def go(rt) -> str:
            tasks = TaskStore(rt.store, rt.paths.data / "tasks").list()
            if not tasks:
                return "No open tasks."
            return "\n".join(f"{t.id} [{t.state}] {t.title}" + (f" (step: {t.current_step})" if t.current_step else "")
                             for t in tasks[:30])
        return self._with_rt(go)

    def cmd_task(self, task_id: str) -> str:
        from jarvis.tasks.store import TaskStore

        def go(rt) -> str:
            store = TaskStore(rt.store, rt.paths.data / "tasks")
            t = store.get(task_id.strip())
            if not t:
                return f"No task {task_id}."
            u = store.usage(t.id)
            lines = [f"{t.id} [{t.state}] {t.title}", f"Goal: {t.goal}", f"Owner: {t.owner}, priority {t.priority}"]
            if t.deadline:
                lines.append(f"Deadline: {t.deadline}")
            if t.current_step:
                lines.append(f"Step: {t.current_step}")
            if t.last_error:
                lines.append(f"Last error: {t.last_error} (retries {t.retries})")
            lines.append(f"Model calls: {u['calls']}, notional ${u['notional_usd']}")
            for e in store.events(t.id)[-5:]:
                lines.append(f"  {e['ts']} {e['kind']}")
            return "\n".join(lines)
        return self._with_rt(go)

    def cmd_task_state(self, task_id: str, state: str) -> str:
        from jarvis.tasks.store import TaskStore, TransitionError

        def go(rt) -> str:
            try:
                t = TaskStore(rt.store, rt.paths.data / "tasks").set_state(task_id.strip(), state, "telegram")
            except KeyError:
                return f"No task {task_id}."
            except TransitionError as e:
                return f"Not possible: {e}"
            return f"{t.id} is now {t.state}."
        return self._with_rt(go)

    # ---- schedules ----

    def cmd_schedules(self) -> str:
        def go(rt) -> str:
            items = ScheduleStore(rt.store.conn).list()
            return "\n".join(s.line() for s in items) or "No schedules."
        return self._with_rt(go)

    def draft_schedule(self, text: str) -> tuple[str, str | None]:
        """(text to show, draft token or None). Saved only after the Save button."""
        if not text.strip():
            return "Say what and when, e.g. /schedule every Monday at 9 project summary", None
        try:
            draft = self.p.draft(text)
        except ScheduleParseError as e:
            return e.question, None
        token = secrets.token_hex(6)
        with self._drafts_lock:
            now = time.monotonic()
            self._drafts = {k: v for k, v in self._drafts.items() if now - v.created < DRAFT_TTL_SECONDS}
            self._drafts[token] = _Draft(draft, now)
        return draft.show(self.p.now()) + "\n\nSave this schedule?", token

    def confirm_schedule(self, token: str, save: bool) -> str:
        with self._drafts_lock:
            d = self._drafts.pop(token, None)
        if d is None or time.monotonic() - d.created >= DRAFT_TTL_SECONDS:
            return "That draft expired. Send /schedule again."
        if not save:
            return "Not saved."
        s = self.p.save(d.draft, source="telegram")
        return f"Saved as {s.id}: {d.draft.description}."

    def cmd_schedule_action(self, action: str, sid: str) -> str:
        sid = sid.strip()

        def go(rt) -> str:
            store = ScheduleStore(rt.store.conn)
            if not store.get(sid):
                return f"No schedule {sid}."
            if action == "delete":
                store.delete(sid)
            else:
                store.set_enabled(sid, action == "resume", self.p.now())
            rt.audit.write("schedule_" + action, schedule_id=sid, source="telegram")
            return f"{sid}: {action}d." if action != "pause" else f"{sid}: paused."
        if action == "run":
            r = self.p.runner().run(sid, "run-now")
            return f"{sid} ran: {r.status}." + (f"\n{r.text}" if r.text and self.p.notifier is None else "")
        return self._with_rt(go)

    def cmd_approvals(self) -> str:
        def go(rt) -> str:
            items = PendingApprovals(rt.store.conn).list()
            if not items:
                return "Nothing waiting."
            return "\n\n".join(f"#{a['id']} from {a['schedule_id']} ({a['created_at'][:16]}): {a['tool']} "
                               f"[{a['tier']}]\n{a['arguments']}" for a in items[:15]) + \
                "\n\nThese did not run. /approve <id> runs that exact action once; /deny <id> drops it."
        return self._with_rt(go)

    def pending_approval_ids(self) -> list[int]:
        return self._with_rt(lambda rt: [a["id"] for a in PendingApprovals(rt.store.conn).list()[:15]])  # type: ignore[arg-type,return-value]

    @staticmethod
    def _pid(text: str) -> int | None:
        t = text.strip().lstrip("#")
        return int(t) if t.isdigit() else None

    def cmd_approve(self, pid: str) -> str:
        """Replays the exact queued call once (jarvis/proactive/replay.py); the result also goes to the notifier."""
        n = self._pid(pid)
        if n is None:
            return "Usage: /approve <id> (see /approvals)"
        return self.p.approve_pending(n, source="telegram").message

    def cmd_deny(self, pid: str) -> str:
        n = self._pid(pid)
        if n is None:
            return "Usage: /deny <id> (see /approvals)"
        return self.p.deny_pending(n, source="telegram").message

    def cmd_dismiss(self, pid: str) -> str:
        def go(rt) -> str:
            ok = pid.strip().lstrip("#").isdigit() and PendingApprovals(rt.store.conn).dismiss(int(pid.strip().lstrip("#")))
            return f"Dismissed #{pid.strip().lstrip('#')}." if ok else f"No pending approval {pid}."
        return self._with_rt(go)

    # ---- reminders and brief ----

    def cmd_remind(self, text: str) -> str:
        parsed = parse_reminder(text, self.p.now())
        if not parsed:
            return "I could not read when. Try: /remind in 10 minutes call back, or /remind tomorrow at 9 pay rent."

        def go(rt) -> str:
            r = ReminderStore(rt.store.conn, rt.audit).add(parsed.text, parsed.due, "telegram", self.p.now())
            return f"Reminder #{r.id} set for {r.due_at:%a %d %b %H:%M}: {r.text}"
        return self._with_rt(go)

    def cmd_reminders(self) -> str:
        def go(rt) -> str:
            items = ReminderStore(rt.store.conn).pending()
            return "\n".join(f"#{r.id} {r.due_at:%a %d %b %H:%M} {r.text}" for r in items) or "No pending reminders."
        return self._with_rt(go)

    def cmd_brief(self) -> str:
        return self.p.brief_text()

    # ---- chat (chat thread only) ----

    def chat(self, text: str, approver: Approver) -> str:
        if self.stop.engaged():
            return "Emergency stop is ON. /resume first."
        try:
            if self._session is None:
                self._rt = self.p.open_rt()
                self._session = self.p.chat(self._rt, approver)
            return self._session.send(text)
        except RoutingError as e:
            self._drop_session()
            return f"No AI model is allowed right now ({e})."
        except ProviderError as e:
            return f"Model error ({e.kind}): {e}"
        except EmergencyStop as e:
            return f"Stopped: {e}"

    def new_session(self) -> str:
        learned = self._drop_session(extract=True)
        return "New conversation." + (f" Learned: {learned}." if learned else "")

    def _drop_session(self, extract: bool = False) -> str:
        session, rt = self._session, self._rt
        self._session = self._rt = None
        learned = ""
        if session is not None and extract:
            try:
                saved = [mid for action, mid in session.end() if action in ("ADD", "UPDATE", "SUPERSEDE")]
                learned = ", ".join(saved)
            except (ProviderError, EmergencyStop):
                pass
        if rt is not None:
            rt.close()
        return learned
