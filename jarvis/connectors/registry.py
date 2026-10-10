"""Connector entries, tools and health checks (PLAN.md section 13, "Connector and MCP registry").

For the lead to merge:
  connector_tools(deps)       -> list[Tool]   register each into the ToolRegistry
  connector_health(deps)      -> list[(name, ok, detail)]   for `jarvis connectors status`
  write_connector_registry()  adds connector sections to <home>/connectors/registry.yaml
  apply_connector_registry()  applies Sachin's settings there (disable / raise a tier;
                              lowering is ignored, same rule as the built-in tools)

Tool tiers are declared in CONNECTORS. A tool that is not listed there (a new connector
or tool nobody classified yet) gets T2 and no agent access (PLAN.md rule).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from jarvis.connectors import eventkit
from jarvis.connectors.config import load_connectors_config
from jarvis.connectors.google import auth as google_auth
from jarvis.connectors.google.client import GoogleClient, GoogleError
from jarvis.connectors.google.tools import GoogleTools
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.docs.library import DocLibrary
from jarvis.docs.tools import make_doc_search
from jarvis.tools.registry import TIERS, Tool, ToolRegistry

DEFAULT_TIER = "T2"
NO_AGENTS: list[str] = []

# Declared connectors. "agents" = who may use the tools besides the main Jarvis loop.
CONNECTORS: dict[str, dict] = {
    "documents": {
        "type": "native", "source": "jarvis/docs", "auth": None,
        "tools": {"doc_search": {"tier": "T0", "agents": ["jarvis", "researcher", "writer", "checker"]}},
    },
    "google": {
        "type": "direct-api", "source": "google-api-python-client (Calendar v3, Gmail v1)",
        "auth": {"keyring_item": google_auth.TOKEN_SECRET, "scopes": google_auth.SCOPES},
        "tools": {
            "parse_time": {"tier": "T0", "agents": ["jarvis", "researcher", "writer", "checker"]},
            "calendar_list": {"tier": "T0", "agents": ["jarvis"]},
            "calendar_create_event": {"tier": "T2", "agents": ["jarvis"]},
            "gmail_search": {"tier": "T0", "agents": ["jarvis"]},
            "gmail_read": {"tier": "T0", "agents": ["jarvis"]},
            "gmail_draft": {"tier": "T1", "agents": ["jarvis"]},
            "gmail_send": {"tier": "T3", "agents": ["jarvis"]},
        },
    },
    "eventkit": {
        "type": "native", "source": "pyobjc-framework-EventKit (macOS only)", "auth": {"macos_permission": "Reminders"},
        # Not classified by Sachin yet: T2 and no agent access.
        "tools": {"reminders_list": {"tier": "T2", "agents": NO_AGENTS, "unclassified": True},
                  "reminder_create": {"tier": "T2", "agents": NO_AGENTS, "unclassified": True}},
    },
}


def declared(tool_name: str) -> dict:
    for entry in CONNECTORS.values():
        if tool_name in entry["tools"]:
            return entry["tools"][tool_name]
    return {"tier": DEFAULT_TIER, "agents": NO_AGENTS, "unclassified": True}


@dataclass
class ConnectorDeps:
    home: Path
    store: Store
    audit: AuditLog
    max_privacy: str = "P1"
    cfg: dict = field(default_factory=load_connectors_config)
    google_client: Callable[[], GoogleClient | None] | None = None   # None = real client when connected
    eventkit_client: Callable[[], eventkit.EventKitClient | None] | None = None  # None = Mac client on macOS
    now: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())


def default_google_client(cfg: dict) -> Callable[[], GoogleClient | None]:
    def make() -> GoogleClient | None:
        if not google_auth.load_token():
            return None
        try:
            from jarvis.connectors.google.api import GoogleApiClient
            return GoogleApiClient(google_auth.credentials(cfg))
        except (google_auth.GoogleAuthError, GoogleError):
            return None
    return make


def doc_library(deps: ConnectorDeps) -> DocLibrary:
    docs = deps.cfg.get("docs") or {}
    return DocLibrary(deps.home, deps.store, chunk_chars=int(docs.get("chunk_chars") or 900),
                      overlap=int(docs.get("overlap") or 150),
                      max_file_bytes=int(docs.get("max_file_mb") or 50) * 1024 * 1024)


def _with_declared_tier(tool: Tool) -> Tool:
    """The tier in CONNECTORS wins; anything undeclared falls back to T2 (never lower than the code's tier)."""
    tier = declared(tool.spec.name)["tier"]
    if TIERS.index(tier) < TIERS.index(tool.tier):
        tier = tool.tier
    return tool if tier == tool.tier else replace(tool, tier=tier)


def connector_tools(deps: ConnectorDeps) -> list[Tool]:
    tools: list[Tool] = [make_doc_search(doc_library(deps), deps.max_privacy)]
    if (deps.cfg.get("google") or {}).get("enabled", True):
        factory = deps.google_client or default_google_client(deps.cfg)
        tools += GoogleTools(factory, deps.cfg, deps.max_privacy, now=deps.now).tools()
    ek_enabled = (deps.cfg.get("eventkit") or {}).get("enabled", True)
    if ek_enabled and (deps.eventkit_client is not None or eventkit.is_supported()):
        tools += eventkit.EventKitTools(deps.eventkit_client or eventkit.default_client,
                                        deps.cfg.get("timezone") or "Asia/Kolkata").tools()
    return [_with_declared_tier(t) for t in tools]


# ---- health ----

_CHECKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS connector_checks (
    name TEXT PRIMARY KEY,
    ok INTEGER NOT NULL,
    detail TEXT,
    checked_at TEXT NOT NULL
);
"""


def _record(store: Store, name: str, ok: bool, detail: str) -> None:
    store.conn.executescript(_CHECKS_SCHEMA)
    store.conn.execute(
        "INSERT OR REPLACE INTO connector_checks (name, ok, detail, checked_at) VALUES (?, ?, ?, ?)",
        (name, int(ok), detail, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    store.conn.commit()


def last_check(store: Store, name: str) -> tuple[bool, str, str] | None:
    store.conn.executescript(_CHECKS_SCHEMA)
    row = store.conn.execute("SELECT ok, detail, checked_at FROM connector_checks WHERE name=?", (name,)).fetchone()
    return (bool(row[0]), row[1], row[2]) if row else None


def connector_health(deps: ConnectorDeps, live: bool = False) -> list[tuple[str, bool, str]]:
    """Offline checks always; with live=True also one small Google call (recorded as the last check)."""
    out: list[tuple[str, bool, str]] = []
    cfg = deps.cfg

    lib = doc_library(deps)
    docs = lib.documents()
    failed = [d for d in docs if d.status != "ok"]
    private = sum(1 for d in docs if d.privacy == "P2")
    out.append(("documents", not failed,
                f"{len(lib.projects())} projects, {len(docs)} documents ({private} private), "
                f"{sum(d.chunks for d in docs)} chunks" + (f"; {len(failed)} without text or failed" if failed else "")))

    g = cfg.get("google") or {}
    if not g.get("enabled", True):
        out.append(("google", True, "disabled in config"))
    else:
        path = google_auth.client_secret_path(cfg)
        if not path:
            out.append(("google client file", False, "not set (google.client_secret_file in config/local.yaml)"))
        elif not path.is_file():
            out.append(("google client file", False, f"missing: {path}"))
        else:
            out.append(("google client file", True, "found"))
        ok, detail = google_auth.token_status(cfg)
        out.append(("google token", ok, detail))
        try:
            import googleapiclient  # noqa: F401
            import google_auth_oauthlib  # noqa: F401
            out.append(("google libraries", True, "installed"))
        except ImportError:
            out.append(("google libraries", False, "pip install google-api-python-client google-auth-oauthlib"))
        if live:
            client = (deps.google_client or default_google_client(cfg))()
            if client is None:
                ok, detail = False, "cannot connect (token or client file missing)"
            else:
                try:
                    ok, detail = True, client.ping()
                except GoogleError as e:
                    ok, detail = False, str(e)
            _record(deps.store, "google", ok, detail)
        prev = last_check(deps.store, "google")
        if prev:
            out.append(("google last check", prev[0], f"{prev[2]}: {prev[1]}"))

    if (cfg.get("eventkit") or {}).get("enabled", True):
        ok, detail = eventkit.health(deps.eventkit_client or eventkit.default_client)
        out.append(("eventkit", ok, detail))
    return out


# ---- private registry file (<home>/connectors/registry.yaml) ----

def write_connector_registry(tools: list[Tool], path: Path) -> None:
    """Add connector sections; keep Sachin's existing settings. Never stores secrets."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data if isinstance(data, dict) else {}
    section = data.setdefault("connectors", {})
    names = {t.spec.name for t in tools}
    for cname, entry in CONNECTORS.items():
        listed = {n: v for n, v in entry["tools"].items() if n in names}
        if not listed:
            continue
        c = section.setdefault(cname, {})
        c.setdefault("type", entry["type"])
        c.setdefault("source", entry["source"])
        if entry["auth"]:
            c.setdefault("auth", json.loads(json.dumps(entry["auth"])))
        c.setdefault("health", "jarvis connectors status")
        tool_entries = c.setdefault("tools", {})
        for n, v in listed.items():
            tool_entries.setdefault(n, {"tier": v["tier"], "enabled": True, "agents": list(v["agents"])})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Jarvis connector and tool registry (private, not in git).\n"
                    "# You may set enabled: false or raise a tier. Lowering a tier is ignored.\n"
                    + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def apply_connector_registry(reg: ToolRegistry, path: Path, audit: AuditLog) -> None:
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for cname in CONNECTORS:
        entries = ((((data.get("connectors") or {}).get(cname) or {}).get("tools")) or {}) if isinstance(data, dict) else {}
        for name, entry in entries.items():
            tool = reg.get(name)
            if not tool or not isinstance(entry, dict):
                continue
            tier, enabled = entry.get("tier", tool.tier), entry.get("enabled", True)
            if tier not in TIERS or TIERS.index(tier) < TIERS.index(tool.tier):
                if tier != tool.tier:
                    audit.write("registry_tier_ignored", tool=name, wanted=tier, kept=tool.tier)
                tier = tool.tier
            if tier != tool.tier or enabled is False:
                reg.register(replace(tool, tier=tier, enabled=bool(enabled)))
