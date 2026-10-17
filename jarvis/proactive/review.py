"""Nightly review: what happened today, written to memory/episodes/YYYY-MM-DD.md.

From the Hermes masterclass review (PROGRESS.md, 2026-10-10). Deterministic and local: it reads
the task, schedule, trigger and approval records and the memory files; no model is called and
nothing leaves the computer. The episode file is plain markdown (the memory index only reads
m-*.md files, so it does not disturb memory search). Re-running on the same day replaces only
the generated section, so notes Sachin adds to the file are kept.

The run's own output (Telegram or file) carries counts only; titles stay in the episode file.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from jarvis.memory.conflicts import find_conflicts
from jarvis.memory.store import MemoryStore
from jarvis.proactive.guard import usage_today

START = "<!-- nightly-review:start -->"
END = "<!-- nightly-review:end -->"


@dataclass
class ReviewResult:
    path: Path
    summary: str
    conflicts: int


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[tuple]:
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _on_day(value: str | None, day: date, tz) -> bool:
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # SQLite datetime('now') is UTC
    return dt.astimezone(tz).date() == day


def episode_path(home: Path, day: date) -> Path:
    return home / "memory" / "episodes" / f"{day.isoformat()}.md"


def nightly_review(home: Path, conn: sqlite3.Connection, memory: MemoryStore, now: datetime) -> ReviewResult:
    tz, day = now.tzinfo, now.date()
    prefilter = (day - timedelta(days=1)).isoformat()

    tasks = [(tid, title, state) for tid, title, state, upd in
             _rows(conn, "SELECT id, title, state, updated_at FROM tasks WHERE updated_at >= ?", (prefilter,))
             if _on_day(upd, day, tz)]
    runs = [(sid, name, status) for sid, name, status, started in
            _rows(conn, "SELECT r.schedule_id, COALESCE(s.name, r.schedule_id), r.status, r.started_at "
                        "FROM sched_runs r LEFT JOIN sched_schedules s ON s.id = r.schedule_id "
                        "WHERE r.started_at >= ?", (prefilter,))
            if _on_day(started, day, tz)]
    fires = [(tid, status) for tid, status, started in
             _rows(conn, "SELECT trigger_id, status, started_at FROM trig_fires WHERE started_at >= ?", (prefilter,))
             if _on_day(started, day, tz)]
    pending = (_rows(conn, "SELECT COUNT(*) FROM sched_pending_approvals WHERE status='pending'") or [(0,)])[0][0]
    active = memory.list(status="active")
    new_memories = [m for m in active if m.valid_from == day.isoformat()]
    conflicts = find_conflicts(active)
    usage = usage_today(conn, now)

    run_counts = Counter(status for _, _, status in runs)
    failed_runs = sorted({name for _, name, status in runs if status in ("failed", "budget")})
    fire_counts = Counter(status for _, status in fires)
    task_counts = Counter(state for _, _, state in tasks)

    lines = [START, f"## Nightly review (generated {now:%H:%M})", ""]
    lines.append(f"**Tasks touched today:** {len(tasks)}" + (f" ({_counts(task_counts)})" if tasks else ""))
    lines += [f"- {tid} {title} — {state}" for tid, title, state in tasks[:30]]
    lines.append("")
    lines.append(f"**Scheduled runs:** {len(runs)}" + (f" ({_counts(run_counts)})" if runs else ""))
    if failed_runs:
        lines.append("- Failed or over budget: " + ", ".join(failed_runs))
    lines.append(f"**Trigger actions:** {len(fires)}" + (f" ({_counts(fire_counts)})" if fires else ""))
    lines.append(f"**Approvals waiting:** {pending}")
    lines.append(f"**Unattended model use today:** {usage.line()}")
    lines.append("")
    lines.append(f"**New memories today:** {len(new_memories)}")
    lines += [f"- [{m.id}] {m.name}" for m in new_memories[:30]]
    lines.append(f"**Possible memory conflicts:** {len(conflicts)}")
    lines += [f"- {c.line()}" for c in conflicts[:20]]
    if conflicts:
        lines.append("  Check them with `jarvis memory conflicts`; supersede or archive the outdated one.")
    truth_line = _truth_check(home, conn)
    lines.append(f"**Index against files:** {truth_line}")
    lines.append(END)
    section = "\n".join(lines)

    path = episode_path(home, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if START in old and END in old:
            before, rest = old.split(START, 1)
            after = rest.split(END, 1)[1]
            text = before + section + after
        else:
            text = old.rstrip() + "\n\n" + section + "\n"
    else:
        text = f"# {day.isoformat()}\n\n{section}\n"
    path.write_text(text, encoding="utf-8")

    summary = (f"Nightly review saved ({path.name}): {len(tasks)} task(s), {len(runs)} scheduled run(s), "
               f"{len(fires)} trigger action(s), {pending} approval(s) waiting, {len(new_memories)} new memory(ies), "
               f"{len(conflicts)} possible memory conflict(s). {truth_line}.")
    return ReviewResult(path, summary, len(conflicts))


def _truth_check(home: Path, conn: sqlite3.Connection) -> str:
    """The nightly index-versus-files cross-check (PLAN.md 27.12): one line, a report, never a repair."""
    from jarvis.core.rebuild import verify

    try:
        return verify(home, conn).summary()
    except Exception as e:  # noqa: BLE001 - the review must still be written
        return f"truth check failed: {type(e).__name__}: {e}"


def _counts(c: Counter) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


class MemoryConflictsSection:
    """Morning-brief section: counts only (memory content stays on this computer)."""
    key, title, order = "memory_conflicts", "Memory to check", 80

    def render(self, ctx) -> str | None:
        memory = MemoryStore(ctx.home, ctx.store)
        n = len(find_conflicts(memory.list(status="active")))
        if not n:
            return None
        return f"- {n} possible memory conflict(s). Check: jarvis memory conflicts"
