"""Task receipt (PLAN.md 10.2). Facts come from the task events, tool runs, approvals and
model usage in SQLite, never from a model. A model writes only the two-line summary, and
a template is used if that call fails."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import LLMRequest, Message, ProviderError
from jarvis.routing.policy import decide
from jarvis.schema import validate

if TYPE_CHECKING:
    from jarvis.agents.orchestrator import TaskRunner

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object", "properties": {"summary": {"type": "string"}},
    "required": ["summary"], "additionalProperties": False,
}


def _minutes(start: str, end: str) -> str:
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        mins = (b - a).total_seconds() / 60
        return f"{mins:.0f} min" if mins >= 1 else f"{(b - a).total_seconds():.0f} s"
    except (ValueError, TypeError):
        return "?"


def build_receipt(runner: "TaskRunner", task_id: str, summary: str | None = None) -> str:
    tasks, conn = runner.tasks, runner.store.conn
    task = tasks.get(task_id)
    assert task
    usage = tasks.usage(task_id)
    events = tasks.events(task_id)
    runs = conn.execute("SELECT agent, tool, tier, ok, arguments FROM tool_runs WHERE task_id=? ORDER BY id",
                        (task_id,)).fetchall()
    approvals = conn.execute("SELECT action, decision FROM approvals WHERE task_id=? ORDER BY id", (task_id,)).fetchall()

    lines = [f"{task.state} · {task.id} · {task.title} · {_minutes(task.created_at, task.updated_at)} · "
             f"{usage['calls']} model calls · ${usage['notional_usd']:.2f} notional"
             + (f" (${usage['billed_usd']:.2f} billed)" if usage["billed_usd"] else " (subscription, not billed per call)"),
             ""]
    if summary:
        lines += [summary, ""]
    lines.append(f"Goal: {task.goal}")
    if task.project:
        lines.append(f"Project: {task.project}")
    plan = task.plan or {}
    if plan:
        team = f"{len(plan.get('research', []))} researchers, writer, checker" if plan.get("use_team") else "Jarvis alone"
        lines.append(f"Plan: {team}")

    lines += ["", "What was done:"]
    per_agent: dict[str, Counter] = {}
    for agent, tool, tier, ok, _ in runs:
        per_agent.setdefault(agent or "jarvis", Counter())[f"{tool}{'' if ok else ' (failed/refused)'}"] += 1
    for agent, counts in per_agent.items():
        lines.append(f"- {agent}: " + ", ".join(f"{t} x{n}" for t, n in counts.items()))
    if not per_agent:
        lines.append("- no tools used")

    files = [e["detail"] for e in events if e["kind"] == "output"]
    created = [json.loads(a).get("path") for agent, tool, tier, ok, a in runs if tool == "write_file" and ok]
    if created or files:
        lines += ["", "Files:"]
        lines += [f"- created {p} (task folder)" for p in created if p]
        lines += [f"- copied to {f['file']}" for f in files if isinstance(f, dict)]

    verifies = [e["detail"] for e in events if e["kind"] == "verify" and isinstance(e["detail"], dict)]
    if verifies:
        lines += ["", "Verification:"]
        for i, v in enumerate(verifies, 1):
            lines.append(f"- round {i}: {'PASS' if v['passed'] else 'FAIL'}")
            for c in v.get("checks", []):
                by = " (checker)" if c.get("by") == "checker" else ""
                note = f" - {c['note']}" if c.get("note") else ""
                lines.append(f"  - [{'x' if c['passed'] else ' '}] {c['check']}{by}{note}")
            for p in v.get("problems", []):
                lines.append(f"  - problem: {p}")

    lines += ["", "Approvals:"]
    if approvals:
        for action, decision in approvals:
            tool = json.loads(action).get("tool", "?")
            lines.append(f"- {tool}: {decision}")
    else:
        lines.append("- none needed")

    fallbacks = [e for e in events if e["kind"] == "plan_fallback"]
    lines += ["", "Models: " + (", ".join(usage["models"]) or "none")
              + (" (planner fell back to solo)" if fallbacks else "")]
    lines.append(f"Tokens: {usage['input_tokens']:,} in, {usage['output_tokens']:,} out")
    if task.last_error and task.state != "COMPLETED":
        lines += ["", f"Error: {task.last_error}"]
    lines += ["", "Remaining: " + ("nothing" if task.state == "COMPLETED" else
                                   "resume with: jarvis task run " + task.id if task.state == "PAUSED" else "see error above")]
    return "\n".join(lines) + "\n"


def _summary(runner: "TaskRunner", task_id: str, facts: str) -> str | None:
    try:
        d = decide(runner.config, "task_summary", runner.provider_override)
        req = LLMRequest(route="task_summary", model=d.model,
                         system=(PROMPTS_DIR / "task_summary.md").read_text(encoding="utf-8"),
                         messages=[Message.text("user", facts[:6000])], reasoning=d.effort,  # type: ignore[arg-type]
                         response_schema=SUMMARY_SCHEMA, task_id=task_id)
        res = runner.provider_for(d).structured(req, SUMMARY_SCHEMA)
        runner.store.record_usage(None, "task_summary", res.response, task_id=task_id)
        if res.valid and validate(res.data, SUMMARY_SCHEMA):
            return str(res.data["summary"]).strip()[:400]  # type: ignore[index]
    except (ProviderError, NotImplementedError, Exception):  # the receipt must never fail
        return None
    return None


def write_receipt(runner: "TaskRunner", task_id: str) -> Path:
    facts = build_receipt(runner, task_id)
    summary = _summary(runner, task_id, facts)
    path = runner.tasks.folder(task_id) / "receipt.md"
    path.write_text(build_receipt(runner, task_id, summary), encoding="utf-8")
    runner.tasks.event(task_id, "receipt", str(path))
    return path
