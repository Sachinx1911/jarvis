"""The `teardown` tool: the brain starts a job from a typed sentence ("reverse engineer Stripe's
homepage"). T1: a read-only observation of a public page, but the result carries page-derived
text, so it taints the session like any web tool (fail-closed default in the registry).

The lead registers it in jarvis/tools/catalog.py:
    from jarvis.xray.tools import xray_tools
    for t in xray_tools(d.home, d.store, d.audit, memory=d.memory): add(t)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolSpec
from jarvis.tools.registry import Tool
from jarvis.xray.spoken import parse_spoken_address
from jarvis.xray.teardown import TeardownBusy, TeardownError, host_of, run_teardown

PARAMS = {"type": "object",
          "properties": {"url": {"type": "string"},
                         "question": {"type": "string"}},
          "required": ["url"]}


def xray_tools(home: Path, store: Store, audit: AuditLog, memory: Any = None,
               deps_factory: Callable[[], Any] | None = None, diag: Callable[[], dict] | None = None) -> list[Tool]:
    """The tools of Phase 9. deps_factory/diag default to the live kit (jarvis.xray.live) and are
    only called when the tool runs, never at registration."""

    def _diag() -> dict:
        if diag is not None:
            return diag()
        from jarvis.xray.live import kit_diag

        return kit_diag()

    def _deps() -> Any:
        if deps_factory is not None:
            return deps_factory()
        from jarvis.xray.live import live_deps

        return live_deps(home, store, audit, memory=memory)

    def teardown(args: dict) -> str:
        url = parse_spoken_address(str(args.get("url", ""))) or str(args.get("url", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            return f"Not a web address: {args.get('url', '')!r}. Give the site's address (for example https://igloo.inc)."
        d = _diag()
        if not d.get("ready"):
            from jarvis.xray.live import problems_text

            return f"The teardown kit is not ready: {problems_text(d)}. The user can run: jarvis xray diag"
        try:
            deps = _deps()
        except ImportError as e:
            return f"The teardown kit is not available: {e}"
        try:
            res = run_teardown(url, str(args.get("question", "")), deps)
        except TeardownBusy as e:
            return f"Refused: {e}"
        except TeardownError as e:
            return f"The teardown of {host_of(url)} failed: {e}"
        return (f"Teardown of {host_of(url)} written: {res.note_path} (task {res.task_id}, label: {res.label}).\n"
                f"{res.spoken}\n\n{res.summary}")

    spec = ToolSpec("teardown", "Reverse-engineer a public website's front end: what it is built with and how. "
                                "Only when the user asks.", PARAMS)
    return [Tool(spec, "T1", teardown, url_args=("url",), text_args=("question",))]
