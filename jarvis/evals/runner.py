"""Migration evaluation runner (PLAN.md 5.11).

Each task runs in its own temporary Jarvis home, so evals never touch real memory.
Results are written to <home>/data/evals/ (git-ignored) with provider, model, date and
git commit, so runs on different providers can be compared.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from jarvis.control.audit import AuditLog
from jarvis.core.chat import ROUTE, ChatSession
from jarvis.db import Store
from jarvis.memory import extract
from jarvis.memory.extract import Extractor
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryStore
from jarvis.paths import REPO_ROOT
from jarvis.providers import make_provider
from jarvis.providers.base import ProviderError
from jarvis.routing.policy import decide

TASKS_FILE = REPO_ROOT / "tests" / "evals" / "migration" / "tasks.yaml"


@dataclass
class TaskResult:
    task_id: str
    category: str
    language: str
    passed: bool
    detail: str
    output: str = ""


@dataclass
class Report:
    provider: str
    model: str
    results: list[TaskResult] = field(default_factory=list)
    path: Path | None = None

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)


def load_tasks(path: Path = TASKS_FILE) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["tasks"]


def check(task: dict[str, Any], output: str, extracted: int | None) -> tuple[bool, str]:
    c = task.get("checks", {})
    low = output.lower()
    if "contains_any" in c and not any(s.lower() in low for s in c["contains_any"]):
        return False, f"missing any of {c['contains_any']}"
    bad = [s for s in c.get("not_contains", []) if s.lower() in low]
    if bad:
        return False, f"contains {bad}"
    if extracted is not None:
        if extracted < c.get("extract_min", 0):
            return False, f"saved {extracted}, expected at least {c['extract_min']}"
        if "extract_max" in c and extracted > c["extract_max"]:
            return False, f"saved {extracted}, expected at most {c['extract_max']}"
    return True, "ok"


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_task(task: dict[str, Any], config, provider_name: str | None) -> TaskResult:
    with tempfile.TemporaryDirectory(prefix="jarvis-eval-") as tmp:
        home = Path(tmp)
        store = Store(home / "data" / "jarvis.db")
        audit = AuditLog(home / "data" / "audit.jsonl")
        memory = MemoryStore(home, store)
        try:
            for m in task.get("setup", []):
                memory.save(Memory(**m))
            if "extract" in task:
                d = decide(config, extract.ROUTE, provider_name)
                ex = Extractor(memory, make_provider(d.provider, config), d, audit)
                results = ex.extract_session(task["extract"])
                saved = sum(1 for a, _ in results if a in ("ADD", "UPDATE", "SUPERSEDE"))
                ok, detail = check(task, "", saved)
                return TaskResult(task["id"], task["category"], task["language"], ok, detail, json.dumps(results))

            d = decide(config, ROUTE, provider_name)
            hh, mm = (int(x) for x in task.get("time", "12:00").split(":"))
            fixed = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
            session = ChatSession(config, make_provider(d.provider, config), d, store, audit,
                                  now=lambda: fixed, home=home, memory=memory)
            output = ""
            for text in task["input"]:
                output = session.send(text)
            ok, detail = check(task, output, None)
            return TaskResult(task["id"], task["category"], task["language"], ok, detail, output)
        except ProviderError as e:
            return TaskResult(task["id"], task["category"], task["language"], False, f"provider error: {e}")
        finally:
            store.close()


def run_suite(rt, provider_name: str | None = None, category: str | None = None) -> Report:
    d = decide(rt.config, ROUTE, provider_name)
    report = Report(d.provider, d.model)
    for task in load_tasks():
        if category and task["category"] != category:
            continue
        report.results.append(run_task(task, rt.config, provider_name))
    out_dir = rt.paths.data / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report.path = out_dir / f"{stamp}-{d.provider}.jsonl"
    meta = {"provider": d.provider, "model": d.model, "date": stamp, "commit": _git_commit()}
    with report.path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": meta}) + "\n")
        for r in report.results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return report
