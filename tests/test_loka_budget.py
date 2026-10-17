"""Kubera: per-loka daily budgets (jarvis/control/loka_budget.py, PLAN.md 27.4, 27.6 item 6)."""

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.control import loka_budget as lb
from jarvis.control.audit import AuditLog
from jarvis.core.loop import BudgetExceeded
from jarvis.db import Store
from jarvis.providers.base import LLMResponse, Usage
from jarvis.tasks.budget import Budget as TaskBudget, BudgetTracker
from jarvis.workspaces.model import Budget, Workspace

NOW = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, text, title):
        self.sent.append((text, title))
        return "ok"


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "jarvis.db")
    yield store.conn, AuditLog(tmp_path / "audit.jsonl")
    store.close()


def _usage(conn, workspace, usd, when: datetime):
    conn.execute("INSERT INTO model_usage (ts, route, provider, model, notional_usd, workspace) VALUES (?, 'r', 'p', 'm', ?, ?)",
                 (when.strftime("%Y-%m-%d %H:%M:%S"), usd, workspace))
    conn.commit()


def _task(conn, workspace, when: datetime):
    conn.execute("INSERT INTO tasks (id, title, state, created_at, workspace) VALUES (?, 't', 'DONE', ?, ?)",
                 (f"t-{conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]}", when.strftime("%Y-%m-%d %H:%M:%S"),
                  workspace))
    conn.commit()


def _sched_run(conn, workspace, when: datetime, calls: int):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sched_schedules (id TEXT PRIMARY KEY, workspace TEXT NOT NULL DEFAULT 'personal');
    CREATE TABLE IF NOT EXISTS sched_runs (id INTEGER PRIMARY KEY, schedule_id TEXT NOT NULL, started_at TEXT NOT NULL,
        status TEXT NOT NULL, model_calls INTEGER NOT NULL DEFAULT 0, notional_usd REAL NOT NULL DEFAULT 0);
    """)
    sid = f"s-{workspace}"
    conn.execute("INSERT OR IGNORE INTO sched_schedules (id, workspace) VALUES (?, ?)", (sid, workspace))
    conn.execute("INSERT INTO sched_runs (schedule_id, started_at, status, model_calls) VALUES (?, ?, 'ok', ?)",
                 (sid, when.isoformat(), calls))
    conn.commit()


# ---- counting ----

def test_counts_only_this_workspace_and_today(env):
    conn, _ = env
    _usage(conn, "acme", 0.5, NOW - timedelta(hours=1))
    _usage(conn, "acme", 0.25, NOW - timedelta(hours=2))
    _usage(conn, "acme", 9.0, NOW - timedelta(days=1))      # yesterday
    _usage(conn, "personal", 9.0, NOW - timedelta(hours=1))  # another loka
    _task(conn, "acme", NOW - timedelta(hours=3))
    _task(conn, "acme", NOW - timedelta(days=2))
    _sched_run(conn, "acme", NOW - timedelta(hours=1), calls=2)
    _sched_run(conn, "acme", NOW - timedelta(hours=1), calls=0)  # quiet check: not a run
    _sched_run(conn, "personal", NOW - timedelta(hours=1), calls=3)
    u = lb.usage_today(conn, "acme", NOW)
    assert (u.model_calls, u.usd, u.runs) == (2, 0.75, 2)


def test_no_schedule_tables_is_fine(env):
    conn, _ = env
    assert lb.usage_today(conn, "acme", NOW).runs == 0


# ---- caps ----

def test_missing_cap_means_no_cap(env):
    conn, _ = env
    for _ in range(50):
        _usage(conn, "acme", 1.0, NOW)
    assert lb.check(conn, "acme", Budget(), NOW) is None
    assert lb.check(conn, "acme", None, NOW) is None
    assert lb.check(conn, "acme", Budget(max_runs=1), NOW) is None  # runs are not over


@pytest.mark.parametrize("budget,hit", [
    (Budget(max_model_calls=3), "3 model calls"),
    (Budget(max_notional_usd=1.5), "$1.50 notional"),
    (Budget(max_runs=2), "2 runs"),
])
def test_cap_reached(env, budget, hit):
    conn, _ = env
    for _ in range(3):
        _usage(conn, "acme", 0.5, NOW)
    _task(conn, "acme", NOW)
    _task(conn, "acme", NOW)
    reason = lb.check(conn, "acme", budget, NOW)
    assert reason and reason.startswith("loka budget: acme") and hit in reason
    assert lb.allow_unattended(conn, "acme", Workspace("acme", "Acme", budget=budget), NOW) == reason
    assert lb.check(conn, "other", budget, NOW) is None


def test_raw_mapping_accepted(env):
    conn, _ = env
    _usage(conn, "acme", 0.5, NOW)
    assert lb.check(conn, "acme", {"max_model_calls": 1}, NOW)
    assert lb.check(conn, "acme", {"max_model_calls": 0}, NOW) is None  # 0 = no cap, as the global cap reads it


# ---- the running task stops on the same path as its own budget ----

def _resp(usd: float) -> LLMResponse:
    return LLMResponse("", [], "end_turn", Usage(10, 5), "fake", "fake-1", 1, cost_usd=usd)


def test_meter_stops_task_with_loka_reason(env):
    conn, _ = env
    _usage(conn, "acme", 0.9, NOW)  # already spent today
    meter = lb.LokaMeter(conn, "acme", Budget(max_notional_usd=1.0), NOW)
    tracker = BudgetTracker(TaskBudget(max_model_calls=100, max_notional_usd=50.0), extra=meter.charge)
    tracker.charge(_resp(0.05))  # 0.95: still under
    with pytest.raises(BudgetExceeded) as e:
        tracker.charge(_resp(0.1))  # 1.05: over the loka cap, far under the task cap
    assert str(e.value).startswith("loka budget: acme spent $1.05")


def test_task_budget_checked_first(env):
    conn, _ = env
    meter = lb.LokaMeter(conn, "acme", Budget(max_model_calls=1), NOW)
    tracker = BudgetTracker(TaskBudget(max_model_calls=0), extra=meter.charge)
    with pytest.raises(BudgetExceeded) as e:
        tracker.charge(_resp(0.0))
    assert "model call limit" in str(e.value)


def test_meter_without_cap_never_touches_db(env):
    conn, _ = env
    meter = lb.LokaMeter(conn, "acme", Budget(), NOW)
    assert meter.charge(1, 100.0) is None


# ---- notify once a day per loka ----

def test_notify_once_per_day_per_workspace(env):
    conn, audit = env
    n = Notifier()
    assert lb.notify_capped(conn, "acme", "r", n, NOW, audit) is True
    assert lb.notify_capped(conn, "acme", "r", n, NOW + timedelta(hours=2), audit) is False
    assert lb.notify_capped(conn, "beta", "r", n, NOW, audit) is True          # another loka: its own notice
    assert lb.notify_capped(conn, "acme", "r", n, NOW + timedelta(days=1), audit) is True  # tomorrow
    assert len(n.sent) == 3 and "office 'acme'" in n.sent[0][0]
    assert lb.notify_capped(conn, "gamma", "r", None, NOW) is False  # no notifier: nothing sent


def test_notifier_failure_is_swallowed(env):
    conn, _ = env

    class Bad:
        def send(self, *a):
            raise RuntimeError("down")

    assert lb.notify_capped(conn, "acme", "r", Bad(), NOW) is False


# ---- summary for `jarvis workspace show` ----

def test_summary(env):
    conn, _ = env
    _usage(conn, "acme", 0.5, NOW)
    s = lb.summary(conn, "acme", Budget(max_model_calls=10, max_notional_usd=2.0), NOW)
    assert s["used"] == {"runs": 0, "model_calls": 1, "notional_usd": 0.5}
    assert s["caps"] == {"runs": None, "model_calls": 10, "notional_usd": 2.0}
    assert s["over"] is None
    assert s["line"] == "today: 0 runs, 1/10 model calls, $0.50/$2.00 notional"
    assert lb.summary(conn, "acme", None, NOW)["line"] == "today: 0 runs, 1 model calls, $0.50 notional"
