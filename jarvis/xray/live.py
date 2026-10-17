"""The real kit, browser and capture behind a teardown, imported only when a job starts.

kit.py, browser.py and capture.py are built next to this module; nothing here is imported at boot,
so Jarvis answers politely when the kit is missing (`kit_diag` says why). Tests never come here:
they inject fakes into TeardownDeps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.config import Config, load_config
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers import make_provider
from jarvis.tasks.store import TaskStore
from jarvis.xray.teardown import TeardownDeps


def kit_diag() -> dict[str, Any]:
    """{ready, problems, ...} from Kit.diag(); a missing or broken kit module is a problem, not a crash."""
    try:
        from jarvis.xray.kit import Kit
    except ImportError as e:
        return {"ready": False, "problems": [f"the x-ray kit module is not available: {e}"]}
    try:
        diag = Kit().diag()
    except Exception as e:  # noqa: BLE001 (diag must never raise into voice or chat)
        return {"ready": False, "problems": [f"kit diag failed: {type(e).__name__}: {e}"]}
    if not isinstance(diag, dict):
        return {"ready": False, "problems": ["kit diag returned no report"]}
    diag.setdefault("ready", False)
    diag.setdefault("problems", [])
    return diag


def problems_text(diag: dict[str, Any]) -> str:
    problems = [str(p) for p in diag.get("problems") or []]
    return "; ".join(problems) or "unknown problem (run: jarvis xray diag)"


def live_deps(home: Path, store: Store, audit: AuditLog, config: Config | None = None, memory: Any = None,
              docs: Any = None, headless: bool = False, provider_override: str | None = None) -> TeardownDeps:
    """TeardownDeps wired to the real kit and a clean Chrome (jarvis/xray/browser.py). Raises
    ImportError when those modules are not there."""
    from jarvis.xray import browser as browser_mod
    from jarvis.xray import capture as capture_mod
    from jarvis.xray.kit import Kit

    config = config or load_config()
    kit = Kit()
    if docs is None:
        from jarvis.docs.library import DocLibrary

        docs = DocLibrary(home, store)
    if memory is None:
        from jarvis.memory.store import MemoryStore

        memory = MemoryStore(home, store)
    cache: dict[str, Any] = {}

    def provider_for(decision):
        if decision.provider not in cache:
            cache[decision.provider] = make_provider(decision.provider, config)
        return cache[decision.provider]

    def do_capture(url: str, out_dir: Path):
        # Contract with the other half of Phase 9: capture(url, kit, browser, audit, out_dir) -> Capture.
        chrome = kit.find_chrome()
        if not chrome:
            raise XrayError("Google Chrome was not found; install it or put it on PATH")
        browser = browser_mod.CleanBrowser(chrome, headless=headless)   # entered by capture()
        return capture_mod.capture(url, kit, browser, audit, out_dir)

    return TeardownDeps(home=home, store=store, audit=audit, tasks=TaskStore(store, home / "data" / "tasks"),
                        config=config, capture=do_capture, provider_for=provider_for,
                        provider_override=provider_override, memory=memory, docs=docs)
