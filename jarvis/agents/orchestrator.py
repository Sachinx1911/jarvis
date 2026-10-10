"""Jarvis task orchestrator (PLAN.md sections 4, 9, 10).

PLANNED -> RUNNING -> VERIFYING -> COMPLETED / FAILED. Stages are checkpointed in the task,
so a crashed task resumes from its last finished stage.

Team flow: planner -> up to 3 researchers in parallel -> writer -> deterministic checks +
independent checker -> (one revision) -> receipt. Solo flow: Jarvis alone with its tools,
then the same verification. No task is COMPLETED without passing verification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.agents.team import CHECKER, RESEARCHER, WRITER, AgentEnv, WorkOrder, run_agent
from jarvis.config import Config
from jarvis.control.approvals import ApprovalGate, Approver
from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.core.loop import AgentLoop, BudgetExceeded
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.paths import PROMPTS_DIR
from jarvis.projects import ProjectStore
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision, decide
from jarvis.schema import validate
from jarvis.secrets import get_secret
from jarvis.skills.loader import SkillLibrary
from jarvis.tasks.budget import Budget, BudgetTracker
from jarvis.tasks.receipt import write_receipt
from jarvis.tasks.store import Task, TaskStore
from jarvis.tools.catalog import ToolDeps, apply_registry, build_registry, registry_path
from jarvis.tools.quarantine import Quarantine
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "mode": {"type": "string", "enum": ["research", "operate", "code", "answer"]},
        "use_team": {"type": "boolean"},
        "research": {"type": "array", "items": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "focus": {"type": "string"}},
            "required": ["objective", "focus"], "additionalProperties": False}},
        "deliverable": {"type": "object", "properties": {
            "filename": {"type": "string"}, "outline": {"type": "string"}},
            "required": ["filename", "outline"], "additionalProperties": False},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "solo_instructions": {"type": "string"},
    },
    "required": ["title", "use_team", "research", "deliverable", "acceptance_criteria", "solo_instructions"],
    "additionalProperties": False,
}
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "checks": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": {"type": "string"}, "passed": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["criterion", "passed"]}},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["passed", "checks", "problems"],
}


class TaskCancelled(Exception):
    pass


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^a-z0-9-]+", "-", Path(name).stem.lower()).strip("-")[:50] or "report"
    return f"{stem}.md"


def parse_verdict(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if validate(data, VERDICT_SCHEMA) else None


@dataclass
class TaskRunner:
    config: Config
    home: Path
    db_path: Path
    store: Store
    tasks: TaskStore
    audit: AuditLog
    provider_for: Callable[[RouteDecision], ReasoningProvider]
    approver: Approver | None = None
    workers: str | None = None          # worker profile name (config tasks.workers.profiles)
    provider_override: str | None = None  # e.g. "fake" in tests
    web: WebClient | None = None
    progress: Callable[[str], None] = lambda msg: None

    # ---- routing ----

    def decision_for(self, route: str) -> RouteDecision:
        d = decide(self.config, route, self.provider_override)
        if route in ("researcher", "writer") and self.provider_override is None and not os.environ.get("JARVIS_TEST_MODEL"):
            prof = self._worker_profile()
            if prof:
                d = RouteDecision(route, d.provider, prof["model"], prof.get("effort", d.effort),
                                  f"worker profile {self.workers or 'default'}")
        return d

    def _worker_profile(self) -> dict | None:
        cfg = self.config.tasks.get("workers") or {}
        name = self.workers or cfg.get("default")
        prof = (cfg.get("profiles") or {}).get(name or "")
        if self.workers and not prof:
            raise ValueError(f"unknown worker profile: {self.workers}")
        return prof

    def _quarantine(self) -> Quarantine | None:
        try:
            d = decide(self.config, "quarantine", self.provider_override)
        except Exception:
            return None
        return Quarantine(self.provider_for(d), d, self.audit)

    # ---- entry points ----

    def run(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(task_id)
        budget = Budget.from_config(self.config.tasks.get("budget"), task.budget)
        used = self.tasks.usage(task_id)
        self.tracker = BudgetTracker(budget, used["calls"], used["input_tokens"] + used["output_tokens"],
                                     used["notional_usd"])
        self.stop = StopSwitch(self.home / "data")
        self.task_dir = self.tasks.folder(task_id)
        if task.state == "CANCELLED":
            return task
        try:
            self.stop.check()
            if task.state in ("BACKLOG", "FAILED", "PAUSED"):
                task = self.tasks.set_state(task_id, "PLANNED", "planning")
            if not task.plan:
                self._step(task_id, "planning")
                self.tasks.update(task_id, plan=self._plan(task))
                task = self.tasks.get(task_id)  # type: ignore[assignment]
            if task.state == "PLANNED":
                self.tasks.set_state(task_id, "RUNNING")
            if self.tasks.get(task_id).state == "VERIFYING":  # type: ignore[union-attr]
                self.tasks.set_state(task_id, "RUNNING", "resumed during verification")
            mode = task.plan.get("mode")
            if mode == "operate":
                self._run_extra(task_id, "operator")
            elif mode == "code":
                self._run_extra(task_id, "coder")
            elif task.plan.get("use_team"):
                self._run_team(task_id)
            else:
                self._run_solo(task_id)
        except TaskCancelled:
            self.tasks.event(task_id, "cancelled", "stopped at the next step")
            self.progress("Cancelled.")
        except BudgetExceeded as e:
            self._fail(task_id, f"budget: {e}")
        except EmergencyStop as e:
            self._pause(task_id, str(e))
        except ProviderError as e:
            self._fail(task_id, f"model error ({e.kind}): {e}")
        finally:
            final = self.tasks.get(task_id)
            if final and final.state in ("COMPLETED", "FAILED", "CANCELLED", "PAUSED"):
                write_receipt(self, task_id)
        return self.tasks.get(task_id)  # type: ignore[return-value]

    # ---- planning ----

    def _plan(self, task: Task) -> dict[str, Any]:
        d = self.decision_for("planner")
        context = self._project_context(task)
        req = LLMRequest(route="planner", model=d.model, system=(PROMPTS_DIR / "planner.md").read_text(encoding="utf-8"),
                         messages=[Message.text("user", f"Task: {task.goal}{context}")],
                         reasoning=d.effort, response_schema=PLAN_SCHEMA, task_id=task.id)  # type: ignore[arg-type]
        res = self.provider_for(d).structured(req, PLAN_SCHEMA)
        self.store.record_usage(None, "planner", res.response, task_id=task.id)
        self.tracker.charge(res.response)
        if not res.valid or not validate(res.data, PLAN_SCHEMA):
            plan = {"title": task.title, "use_team": False, "research": [],
                    "deliverable": {"filename": "result.md", "outline": "answer"},
                    "acceptance_criteria": ["answers the task"], "solo_instructions": task.goal, "fallback": True}
            self.tasks.event(task.id, "plan_fallback", "planner output invalid; running solo")
        else:
            plan = dict(res.data or {})
            plan["research"] = plan["research"][: int((self.config.tasks.get("team") or {}).get("max_parallel_researchers", 3))]
        plan["deliverable"]["filename"] = _safe_filename(plan["deliverable"]["filename"])
        self.tasks.event(task.id, "plan", plan)
        self.progress(f"Plan: {'team of ' + str(len(plan['research'])) + ' researchers + writer + checker' if plan['use_team'] else 'Jarvis alone'}")
        return plan

    def _project_context(self, task: Task) -> str:
        if not task.project:
            return ""
        text = ProjectStore(self.home).context(task.project)
        return f"\n\nPROJECT {task.project}:\n{text}" if text else ""

    # ---- team ----

    def _env(self) -> AgentEnv:
        task_id = self.task_dir.name
        steps = Budget.from_config(self.config.tasks.get("budget")).max_steps_per_agent
        return AgentEnv(self.config, self.home, self.db_path, self.audit, self.stop, task_id, self.task_dir,
                        self.provider_for, self.decision_for, self._quarantine, self._charge, self.web, steps)

    def _charge(self, resp) -> None:
        self.tracker.charge(resp)
        self._check_cancel()

    def _check_cancel(self) -> None:
        if (self.task_dir / "CANCEL").exists():
            raise TaskCancelled()

    def _run_team(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        assert task
        plan, cp = task.plan, dict(task.checkpoint)
        env = self._env()
        project = self._project_context(task)

        if "research" not in cp:
            self._step(task_id, f"{len(plan['research'])} researchers working")
            orders = [WorkOrder(
                objective=r["objective"], context=f"Overall task: {task.goal}\nYour focus: {r['focus']}{project}",
                output_format="FINDINGS, SOURCES (title - URL), GAPS", stop_condition="you have the facts, or after about 4 searches",
            ) for r in plan["research"]]
            with ThreadPoolExecutor(max_workers=max(1, len(orders))) as pool:
                futures = [pool.submit(run_agent, RESEARCHER, f"researcher-{i + 1}", o, env) for i, o in enumerate(orders)]
                results = [f.result() for f in futures]
            cp["research"] = [r.text for r in results]
            for i, text in enumerate(cp["research"], 1):
                (self.task_dir / f"research-{i}.md").write_text(text, encoding="utf-8")
                self.tasks.event(task_id, "agent_done", {"agent": f"researcher-{i}", "chars": len(text)})
            self.tasks.update(task_id, checkpoint=cp)

        revisions = int((self.config.tasks.get("team") or {}).get("max_revisions", 1))
        problems: list[str] = cp.get("problems", [])
        while True:
            if "report" not in cp or cp.get("needs_revision"):
                version = cp.get("version", 0) + 1
                filename = plan["deliverable"]["filename"]
                if version > 1:
                    filename = filename.replace(".md", f"-v{version}.md")
                self._step(task_id, f"writer drafting {filename}")
                findings = "\n\n".join(f"--- Researcher {i} ---\n{t}" for i, t in enumerate(cp["research"], 1))
                extra = [f"FIX THESE PROBLEMS FROM THE CHECKER:\n- " + "\n- ".join(problems)] if problems else []
                order = WorkOrder(
                    objective=f"Write the report for: {task.goal}",
                    context=f"Outline:\n{plan['deliverable']['outline']}\n\nAcceptance criteria:\n- "
                            + "\n- ".join(plan["acceptance_criteria"]) + f"\n\nFindings:\n{findings}{project}",
                    output_format=f"Create the file {filename} with write_file.",
                    stop_condition="the file is created", extra=extra)
                run_agent(WRITER, "writer", order, env)
                cp.update(report=filename, version=version, needs_revision=False)
                self.tasks.update(task_id, checkpoint=cp)
                self.tasks.event(task_id, "agent_done", {"agent": "writer", "file": filename})

            passed, problems = self._verify(task_id, cp["report"], plan, cp["research"])
            cp["problems"] = problems
            if passed:
                self._complete(task_id, cp["report"])
                return
            if cp["version"] > revisions:
                self._fail(task_id, "verification failed: " + "; ".join(problems)[:500])
                return
            cp["needs_revision"] = True
            self.tasks.update(task_id, checkpoint=cp)
            self.tasks.set_state(task_id, "RUNNING", "revision after checker")
            # The writer cannot invent facts: a follow-up researcher looks up what the checker found missing.
            self._step(task_id, "follow-up research on the checker's findings")
            order = WorkOrder(
                objective="Find the missing or wrong facts listed below, with a source link for each.",
                context=f"Overall task: {task.goal}\n\nWhat the checker found:\n- " + "\n- ".join(problems) + project,
                output_format="FINDINGS, SOURCES (title - URL), GAPS",
                stop_condition="every listed problem has an answer with a source, or no source exists")
            follow = run_agent(RESEARCHER, f"researcher-fix-{cp['version']}", order, env)
            cp["research"] = cp["research"] + [follow.text]
            (self.task_dir / f"research-fix-{cp['version']}.md").write_text(follow.text, encoding="utf-8")
            self.tasks.update(task_id, checkpoint=cp)

    # ---- solo ----

    def _run_solo(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        assert task
        plan, cp = task.plan, dict(task.checkpoint)
        filename = plan["deliverable"]["filename"]
        if "report" not in cp:
            self._step(task_id, "Jarvis working")
            registry = ToolRegistry(self.store, self.audit, ApprovalGate(self.store, self.audit, self._approver(task_id)))
            build_registry(registry, ToolDeps(
                home=self.home, store=self.store, audit=self.audit, memory=MemoryStore(self.home, self.store),
                skills=SkillLibrary(self.home / "skills"), session_id=lambda: task_id, max_privacy="P1",
                tools_config=self.config.tools, web=self.web or WebClient(), quarantine=self._quarantine(),
                tavily_key=lambda: get_secret("tavily_api_key"), system=SystemTools()))
            apply_registry(registry, registry_path(self.home), self.audit)
            d = self.decision_for("main_chat")
            loop = AgentLoop(self.provider_for(d), d, registry, self.store, self.audit, self.stop,
                             max_steps=Budget.from_config(self.config.tasks.get("budget")).max_steps_per_agent,
                             task_id=task_id, on_usage=self._charge, agent="jarvis")
            system = ("You are Jarvis doing a task for the user. Use your tools. Finish with the complete answer "
                      "the user needs, in plain words.\n\nAcceptance criteria:\n- " + "\n- ".join(plan["acceptance_criteria"]))
            result = loop.run([Message.text("user", plan.get("solo_instructions") or task.goal)], system, task_id)
            (self.task_dir / filename).write_text(result.text, encoding="utf-8")
            cp.update(report=filename, version=1)
            self.tasks.update(task_id, checkpoint=cp)
        passed, problems = self._verify(task_id, cp["report"], plan, [], use_checker=len(plan["acceptance_criteria"]) > 1)
        if passed:
            self._complete(task_id, cp["report"])
        else:
            self._fail(task_id, "verification failed: " + "; ".join(problems)[:500])

    def _run_extra(self, task_id: str, role: str) -> None:
        """Operator (computer and named websites, asks Jarvis's approver) or Coder (its own code folder)."""
        from jarvis.agents.extra import CODER, OPERATOR, open_browser_session, run_extra_agent
        from jarvis.browser import domains_from_text

        task = self.tasks.get(task_id)
        assert task
        plan, cp = task.plan, dict(task.checkpoint)
        filename = plan["deliverable"]["filename"]
        if "report" not in cp:
            self._step(task_id, f"{role} working")
            order = WorkOrder(objective=task.goal,
                              context="Acceptance criteria:\n- " + "\n- ".join(plan["acceptance_criteria"])
                              + self._project_context(task),
                              output_format="Finish with a short report of what you did and what you checked.",
                              stop_condition="the task is done and checked, or it cannot be done")
            env = self._env()
            if role == "operator":
                domains = domains_from_text(task.goal)
                browser = open_browser_session(self.home, self.task_dir, domains, audit=self.audit) if domains else None
                try:
                    result = run_extra_agent(OPERATOR, "operator", order, env, approver=self._approver(task_id),
                                             browser=browser)
                finally:
                    if browser is not None:
                        browser.close()
            else:
                project = re.sub(r"[^a-z0-9_-]+", "-", (task.project or task.title).lower()).strip("-")[:40] or "code"
                result = run_extra_agent(CODER, "coder", order, env, coder_project=project)
            (self.task_dir / filename).write_text(result.text, encoding="utf-8")
            cp.update(report=filename, version=1)
            self.tasks.update(task_id, checkpoint=cp)
        passed, problems = self._verify(task_id, cp["report"], plan, [])
        if role == "coder":
            last = self.store.conn.execute(
                "SELECT ok FROM tool_runs WHERE task_id=? AND tool='run_tests' ORDER BY id DESC LIMIT 1",
                (task_id,)).fetchone()
            if not last or not last[0]:
                passed = False
                problems.append("the tests were not run, or the last test run failed")
        if passed:
            self._complete(task_id, cp["report"])
        else:
            self._fail(task_id, "verification failed: " + "; ".join(problems)[:500])

    def _approver(self, task_id: str) -> Approver | None:
        if not self.approver:
            return None
        base = self.approver

        def ask(req):
            self.tasks.set_state(task_id, "WAITING_APPROVAL", req.tool)
            try:
                return base(req)
            finally:
                self.tasks.set_state(task_id, "RUNNING", "approval answered")
        return ask

    # ---- verification ----

    def _verify(self, task_id: str, filename: str, plan: dict, research: list[str],
                use_checker: bool = True) -> tuple[bool, list[str]]:
        self.tasks.set_state(task_id, "VERIFYING")
        self._step(task_id, "checking the work")
        path = self.task_dir / filename
        problems: list[str] = []
        checks: list[dict[str, Any]] = []

        exists = path.is_file() and bool(path.read_text(encoding="utf-8").strip())
        checks.append({"check": "report file exists and is not empty", "passed": exists})
        if not exists:
            problems.append(f"{filename} is missing or empty")
        else:
            text = path.read_text(encoding="utf-8")
            if research:
                seen = self._seen_urls(task_id) | set(URL_RE.findall("\n".join(research)))
                used = {u.rstrip(".,;") for u in URL_RE.findall(text)}
                unknown = sorted(u for u in used if not any(u.startswith(s.rstrip("/")) or s.startswith(u) for s in seen))
                grounded = bool(used) and not unknown
                checks.append({"check": "every link in the report came from the research", "passed": grounded,
                               "note": f"{len(used)} links, unknown: {unknown[:5]}"})
                if not used:
                    problems.append("the report has no source links")
                elif unknown:
                    problems.append("links not found in the research: " + ", ".join(unknown[:5]))

        if exists and use_checker:
            order = WorkOrder(
                objective=f"Verify the report file {filename} for this task: {self.tasks.get(task_id).goal}",  # type: ignore[union-attr]
                context="Acceptance criteria:\n- " + "\n- ".join(plan["acceptance_criteria"]),
                output_format="JSON only: {\"passed\": ..., \"checks\": [...], \"problems\": [...]}")
            result = run_agent(CHECKER, "checker", order, self._env())
            verdict = parse_verdict(result.text)
            if verdict is None:
                problems.append("the checker gave no valid verdict")
                checks.append({"check": "checker verdict", "passed": False, "note": result.text[:200]})
            else:
                checks.extend({"check": c["criterion"], "passed": c["passed"], "note": c.get("note", ""), "by": "checker"}
                              for c in verdict["checks"])
                if not verdict["passed"]:
                    problems.extend(verdict["problems"] or ["checker rejected the report"])
        passed = not problems
        self.tasks.event(task_id, "verify", {"passed": passed, "checks": checks, "problems": problems})
        return passed, problems

    def _seen_urls(self, task_id: str) -> set[str]:
        rows = self.store.conn.execute(
            "SELECT result FROM tool_runs WHERE task_id=? AND ok=1 AND tool IN ('web_search', 'web_fetch')", (task_id,))
        urls: set[str] = set()
        for (result,) in rows:
            urls |= {u.rstrip(".,;") for u in URL_RE.findall(result or "")}
        args = self.store.conn.execute(
            "SELECT arguments FROM tool_runs WHERE task_id=? AND ok=1 AND tool='web_fetch'", (task_id,))
        for (a,) in args:
            urls |= set(URL_RE.findall(a or ""))
        return urls

    # ---- endings ----

    def _complete(self, task_id: str, filename: str) -> None:
        task = self.tasks.get(task_id)
        assert task
        if task.project:
            out = ProjectStore(self.home).outputs(task.project)
            shutil.copy2(self.task_dir / filename, out / filename)
            self.tasks.event(task_id, "output", {"file": str(out / filename)})
        self.tasks.set_state(task_id, "COMPLETED")
        self._step(task_id, "done")

    def _fail(self, task_id: str, error: str) -> None:
        self.tasks.update(task_id, last_error=error, retries=(self.tasks.get(task_id).retries + 1))  # type: ignore[union-attr]
        state = self.tasks.get(task_id).state  # type: ignore[union-attr]
        if state == "VERIFYING" or state in ("RUNNING", "PLANNED", "WAITING_APPROVAL"):
            self.tasks.set_state(task_id, "FAILED", error[:200])
        self.progress(f"Failed: {error}")

    def _pause(self, task_id: str, reason: str) -> None:
        state = self.tasks.get(task_id).state  # type: ignore[union-attr]
        if state in ("RUNNING", "PLANNED", "SCHEDULED"):
            self.tasks.set_state(task_id, "PAUSED", reason)
        elif state == "VERIFYING":
            self.tasks.set_state(task_id, "RUNNING", reason)
            self.tasks.set_state(task_id, "PAUSED", reason)
        self.progress(f"Paused: {reason}")

    def _step(self, task_id: str, text: str) -> None:
        self._check_cancel()
        self.tasks.update(task_id, current_step=text)
        self.tasks.event(task_id, "step", text)
        self.progress(text)
