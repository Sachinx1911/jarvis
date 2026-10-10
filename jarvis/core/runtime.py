"""Wires config, storage, memory, skills and providers together for the CLI."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from jarvis.config import Config, load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ROUTE, ChatSession
from jarvis.db import Store
from jarvis.memory import extract
from jarvis.memory.extract import Extractor
from jarvis.memory.store import MemoryStore
from jarvis.paths import PROMPTS_DIR, JarvisPaths, default_paths
from jarvis.providers import make_provider
from jarvis.routing.policy import RoutingError, decide
from jarvis.skills.loader import SkillLibrary
from jarvis.control.approvals import Approver
from jarvis.tools import quarantine as quarantine_mod
from jarvis.tools.catalog import registry_path, write_registry
from jarvis.tools.quarantine import Quarantine
from jarvis.tools.web import WebClient


@dataclass
class Runtime:
    config: Config
    paths: JarvisPaths
    store: Store
    audit: AuditLog
    memory: MemoryStore
    skills: SkillLibrary

    def close(self) -> None:
        self.store.close()


def open_runtime() -> Runtime:
    paths = default_paths()
    paths.ensure()
    soul = paths.home / "profile" / "SOUL.md"
    if not soul.exists():
        shutil.copyfile(PROMPTS_DIR / "SOUL.example.md", soul)
    store = Store(paths.db)
    memory = MemoryStore(paths.home, store)
    if not (memory.root / "MEMORY.md").exists():
        memory.write_memory_md()
    return Runtime(load_config(), paths, store, AuditLog(paths.audit_log), memory, SkillLibrary(paths.home / "skills"))


def make_extractor(rt: Runtime, provider_override: str | None = None) -> Extractor:
    """The extractor follows its own route; with a provider override it uses that provider."""
    try:
        decision = decide(rt.config, extract.ROUTE, provider_override)
    except RoutingError as e:
        rt.audit.write("routing_error", route=extract.ROUTE, detail=str(e))
        return Extractor(rt.memory, None, None, rt.audit)
    return Extractor(rt.memory, make_provider(decision.provider, rt.config), decision, rt.audit)


def make_quarantine(rt: Runtime, provider_override: str | None = None) -> Quarantine:
    try:
        decision = decide(rt.config, quarantine_mod.ROUTE, provider_override)
    except RoutingError as e:
        rt.audit.write("routing_error", route=quarantine_mod.ROUTE, detail=str(e))
        return Quarantine(None, None, rt.audit)
    return Quarantine(make_provider(decision.provider, rt.config), decision, rt.audit)


def make_chat(rt: Runtime, provider_override: str | None = None, approver: Approver | None = None,
              web: WebClient | None = None) -> ChatSession:
    decision = decide(rt.config, ROUTE, provider_override)  # RoutingError goes to the caller
    session = ChatSession(
        rt.config, make_provider(decision.provider, rt.config), decision, rt.store, rt.audit,
        home=rt.paths.home, memory=rt.memory, skills=rt.skills,
        extractor=make_extractor(rt, provider_override), approver=approver,
        quarantine=make_quarantine(rt, provider_override), web=web,
    )
    write_registry(session.tools, registry_path(rt.paths.home))
    return session


def task_store(rt: Runtime):
    from jarvis.tasks.store import TaskStore

    return TaskStore(rt.store, rt.paths.data / "tasks")


def make_task_runner(rt: Runtime, provider_override: str | None = None, approver: Approver | None = None,
                     workers: str | None = None, progress=None, web: WebClient | None = None):
    from jarvis.agents.orchestrator import TaskRunner

    cache: dict[str, object] = {}

    def provider_for(decision):
        if decision.provider not in cache:
            cache[decision.provider] = make_provider(decision.provider, rt.config)
        return cache[decision.provider]

    return TaskRunner(rt.config, rt.paths.home, rt.paths.db, rt.store, task_store(rt), rt.audit, provider_for,
                      approver=approver, workers=workers, provider_override=provider_override, web=web,
                      progress=progress or (lambda m: None))
