"""Adapters for parts of Jarvis built in other phases (proactive/Telegram, connectors and
document library, voice, cloud switch, event triggers).

Each adapter imports its module lazily and returns {"installed": False, ...} when the module
is missing, so the dashboard tab says "not installed" instead of failing. To wire a module,
give it a function named in HOOKS below that returns a JSON-safe dict; nothing else in the
dashboard has to change. Hooks run inside the request thread and must not call a model.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any, Callable

# Dashboard tab -> (module, hook function inside that module)
# All phases are merged; their dashboard data lives in jarvis/web/hooks.py, except event
# triggers, whose read-only hook ships with the trigger engine itself.
HOOKS: dict[str, tuple[str, str]] = {
    "schedules": ("jarvis.web.hooks", "schedules"),
    "telegram": ("jarvis.web.hooks", "telegram"),
    "connectors": ("jarvis.web.hooks", "connectors"),
    "documents": ("jarvis.web.hooks", "documents"),
    "voice": ("jarvis.web.hooks", "voice"),
    "cloud": ("jarvis.web.hooks", "cloud"),
    "triggers": ("jarvis.proactive.triggers", "dashboard_triggers"),
}


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def call_hook(name: str, home=None) -> dict[str, Any]:
    module, attr = HOOKS[name]
    if not _installed(module):
        return {"installed": False, "module": module, "detail": f"{module} is not installed yet"}
    try:
        mod = importlib.import_module(module)
    except Exception as e:  # a broken module must not take the dashboard down
        return {"installed": False, "module": module, "detail": f"import failed: {type(e).__name__}: {e}"}
    hook: Callable | None = getattr(mod, attr, None)
    if hook is None:
        return {"installed": True, "wired": False, "module": module,
                "detail": f"{module} is installed but has no {attr}() for the dashboard yet"}
    try:
        data = hook(home) if home is not None else hook()
    except Exception as e:
        return {"installed": True, "wired": True, "module": module, "error": f"{type(e).__name__}: {e}"}
    return {"installed": True, "wired": True, "module": module, **(data if isinstance(data, dict) else {"data": data})}


def schedules(home=None) -> dict[str, Any]:
    """Expected hook result: {"items": [{"id", "what", "when", "enabled", "last_run", "next_run"}]}."""
    return call_hook("schedules", home)


def telegram(home=None) -> dict[str, Any]:
    return call_hook("telegram", home)


def connectors(home=None) -> dict[str, Any]:
    """Expected hook result: {"items": [{"name", "type", "enabled", "health", "detail"}]}."""
    return call_hook("connectors", home)


def documents(home=None) -> dict[str, Any]:
    """Expected hook result: {"count": int, "items": [{"id", "title", "class", "project"}]}."""
    return call_hook("documents", home)


def voice(home=None) -> dict[str, Any]:
    return call_hook("voice", home)


def cloud(home=None) -> dict[str, Any]:
    """Expected hook result: {"cloud_allowed": bool, "source": "file|config"}. Read-only here."""
    return call_hook("cloud", home)


def triggers(home=None) -> dict[str, Any]:
    """Expected hook result: {"items": [{"id", "what", "source", "action", "enabled", "every_minutes",
    "cooldown_minutes", "last_check", "next_check", "last_status", "last_detail", "last_fired", "failures"}]}.
    Email rules come without the sender (P2 until decision #19)."""
    return call_hook("triggers", home)
