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


def make_chat(rt: Runtime, provider_override: str | None = None) -> ChatSession:
    decision = decide(rt.config, ROUTE, provider_override)  # RoutingError goes to the caller
    return ChatSession(
        rt.config, make_provider(decision.provider, rt.config), decision, rt.store, rt.audit,
        home=rt.paths.home, memory=rt.memory, skills=rt.skills,
        extractor=make_extractor(rt, provider_override),
    )
