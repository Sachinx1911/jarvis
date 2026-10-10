"""Chat text -> schedule draft. The draft is shown to the user and saved only after a yes.

Order: deterministic rules (timeparse.parse_recurring) first; the model is asked only when
the rules cannot read the text. Model output is never trusted as-is: the cron is
normalised and validated, and an ambiguous answer becomes a question, not a schedule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from jarvis.control.audit import AuditLog
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import redact_p3
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.schema import validate
from jarvis.proactive.timeparse import DAY_NAMES, parse_recurring

ROUTE = "schedule_parser"
KINDS = ("prompt", "skill", "agent", "brief", "heartbeat")
OUTPUTS = ("telegram", "file", "both")

PARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cron": {"type": "string"},
        "what": {"type": "string"},
        "summary": {"type": "string"},
        "ambiguous": {"type": "boolean"},
        "question": {"type": "string"},
    },
    "required": ["cron", "what", "summary", "ambiguous", "question"],
    "additionalProperties": False,
}

_STD_DOW = {"0": "sun", "1": "mon", "2": "tue", "3": "wed", "4": "thu", "5": "fri", "6": "sat", "7": "sun"}


class CronError(ValueError):
    pass


def normalize_cron(expr: str) -> str:
    """Standard 5-field cron -> the same schedule with day NAMES in the day-of-week field.

    APScheduler 3 reads a numeric day-of-week with 0 = Monday, standard cron with
    0 = Sunday. Converting numbers to names keeps the standard meaning. Steps in the
    day-of-week field are refused because they cannot be converted safely.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise CronError("cron needs 5 fields: minute hour day month weekday")
    dow = fields[4].lower()
    if dow not in ("*", "?"):
        if "/" in dow:
            raise CronError("steps in the weekday field are not supported; list the days instead")

        days: list[str] = []
        for item in dow.split(","):
            a, _, b = item.partition("-")
            if a.isdigit() or b.isdigit():
                if not (a in _STD_DOW and (not b or b in _STD_DOW)) or (b and int(a) > int(b)):
                    raise CronError(f"bad weekday: {item}")
                for n in range(int(a), int(b or a) + 1):  # expand: 0-6 -> sun..sat
                    days.append(_STD_DOW[str(n)])
            elif a[:3] in DAY_NAMES and (not b or b[:3] in DAY_NAMES):
                days.append(f"{a[:3]}-{b[:3]}" if b else a[:3])
            else:
                raise CronError(f"bad weekday: {item}")
        fields[4] = ",".join(dict.fromkeys(days))
    else:
        fields[4] = "*"
    norm = " ".join(fields)
    trigger(norm, "UTC")  # raises CronError if APScheduler cannot read it
    return norm


def trigger(cron: str, tz: str) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(cron, timezone=tz)
    except (ValueError, TypeError) as e:
        raise CronError(f"bad cron {cron!r}: {e}") from None


def next_runs(cron: str, tz: str, now: datetime, count: int = 3) -> list[datetime]:
    trig, out, prev = trigger(cron, tz), [], None
    t = now
    for _ in range(count):
        nxt = trig.get_next_fire_time(prev, t)
        if nxt is None:
            break
        out.append(nxt)
        prev, t = nxt, nxt
    return out


@dataclass
class ScheduleDraft:
    name: str
    kind: str
    input: str
    cron: str
    timezone: str
    description: str
    target: str = ""            # skill or agent name
    output: str = "telegram"
    budget: dict[str, Any] = field(default_factory=dict)
    source: str = "rules"       # rules | model | explicit

    def show(self, now: datetime | None = None) -> str:
        what = {"prompt": f"ask Jarvis: {self.input!r}", "skill": f"run skill {self.target!r} with {self.input!r}",
                "agent": f"give agent {self.target!r} the task {self.input!r}", "brief": "send the daily brief",
                "heartbeat": "run the heartbeat check"}[self.kind]
        lines = [f"Schedule: {self.description} ({self.timezone})", f"Runs: {what}", f"Cron: {self.cron}",
                 f"Output: {self.output}", f"Read by: {self.source}"]
        if self.budget:
            lines.append("Budget per run: " + ", ".join(f"{k}={v}" for k, v in self.budget.items()))
        if now is not None:
            runs = next_runs(self.cron, self.timezone, now)
            lines.append("Next: " + ", ".join(r.strftime("%a %d %b %H:%M") for r in runs))
        lines.append("Unattended runs may only read and write new files (T0/T1); anything else waits for approval.")
        return "\n".join(lines)


class ScheduleParseError(ValueError):
    """The text could not be read as a schedule; .question says what to ask the user."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


def _name(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return (clean[:40].rstrip() or "schedule")


class ScheduleParser:
    def __init__(self, tz: str, provider: ReasoningProvider | None = None, decision: RouteDecision | None = None,
                 audit: AuditLog | None = None, store=None):
        self.tz = tz
        self.provider = provider
        self.decision = decision
        self.audit = audit
        self.store = store

    def parse(self, text: str, defaults: dict[str, Any] | None = None) -> ScheduleDraft:
        defaults = defaults or {}
        rec = parse_recurring(text)
        if rec is not None:
            what = rec.rest or text
            return self._draft(what, rec.cron, rec.description, "rules", defaults)
        data = self._ask_model(text)
        if data is None:
            raise ScheduleParseError(
                "I could not read the time. Try e.g. 'every Monday at 9', 'every day at 21:00', 'daily 8am' "
                "or 'roj sakali 8 la'.")
        if data["ambiguous"]:
            raise ScheduleParseError(data["question"] or "When exactly should it run?")
        try:
            cron = normalize_cron(data["cron"])
        except CronError as e:
            raise ScheduleParseError(f"The schedule did not make sense ({e}). Please say the day and time.") from None
        return self._draft(data["what"].strip() or text, cron, data["summary"].strip() or cron, "model", defaults)

    def _draft(self, what: str, cron: str, description: str, source: str, defaults: dict[str, Any]) -> ScheduleDraft:
        return ScheduleDraft(
            name=_name(what), kind=defaults.get("kind", "prompt"), input=what, cron=cron, timezone=self.tz,
            description=description, target=defaults.get("target", ""), output=defaults.get("output", "telegram"),
            budget=dict(defaults.get("budget") or {}), source=source)

    def _ask_model(self, text: str) -> dict[str, Any] | None:
        if not self.provider or not self.decision:
            return None
        clean, _ = redact_p3(text)
        req = LLMRequest(route=ROUTE, model=self.decision.model,
                         system=(PROMPTS_DIR / "schedule_parse.md").read_text(encoding="utf-8"),
                         messages=[Message.text("user", clean)], response_schema=PARSE_SCHEMA,
                         reasoning=self.decision.effort,  # type: ignore[arg-type]
                         privacy_classes=frozenset({"P1"}))
        try:
            res = self.provider.structured(req, PARSE_SCHEMA)
        except (ProviderError, NotImplementedError) as e:
            if self.audit:
                self.audit.write("schedule_parse_error", detail=str(e))
            return None
        if self.store is not None:
            self.store.record_usage(None, ROUTE, res.response)
        if self.audit:
            self.audit.write("model_call", route=ROUTE, provider=res.response.provider, model=res.response.model,
                             input_tokens=res.response.usage.input_tokens,
                             output_tokens=res.response.usage.output_tokens, valid=res.valid)
        if not res.valid or not validate(res.data, PARSE_SCHEMA):
            return None
        return res.data
