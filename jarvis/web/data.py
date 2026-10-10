"""Read models for the dashboard: memories (masked), tasks, agents, tools, usage.

Every function takes an open Runtime from the request thread. Nothing here calls a model.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import yaml

from jarvis.control.audit import AuditLog
from jarvis.core.runtime import Runtime, task_store
from jarvis.memory.model import Memory
from jarvis.privacy import redact_p3
from jarvis.tools.catalog import ToolDeps, apply_registry, build_registry, registry_path, write_registry
from jarvis.tools.registry import TIERS, ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

SENSITIVE = ("sensitive", "secret")
_MASKED_FIELDS = ("name", "body", "subject", "description", "when_to_use", "summary_en", "keywords", "evidence")
EDITABLE_FIELDS = ("name", "type", "body", "subject", "description", "when_to_use", "summary_en", "keywords",
                   "sensitivity", "scope", "expires")


# ---- memory ----

def memory_json(m: Memory, reveal: bool = False) -> dict[str, Any]:
    d = asdict(m)
    masked = m.sensitivity in SENSITIVE and not reveal
    if masked:
        for k in _MASKED_FIELDS:
            d[k] = ""
        d["name"] = "(sensitive)"
    d["masked"] = masked
    return d


def edit_memory(rt: Runtime, memory_id: str, changes: dict[str, Any]) -> Memory:
    mem = rt.memory.get(memory_id)
    if not mem:
        raise KeyError(memory_id)
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"cannot edit: {', '.join(sorted(unknown))}")
    if changes.get("sensitivity") == "secret":
        raise ValueError("secret data is never stored")
    updated = replace(mem, **{k: ("" if v is None else str(v)) for k, v in changes.items()})
    return rt.memory.update(updated)


# ---- tasks ----

def task_json(rt: Runtime, task, running: bool = False, progress: list[str] | None = None) -> dict[str, Any]:
    d = asdict(task)
    d["usage"] = task_store(rt).usage(task.id)
    d["running"] = running
    d["progress"] = (progress or [])[-10:]
    return d


def receipt_text(rt: Runtime, task_id: str) -> str | None:
    path = rt.paths.data / "tasks" / task_id / "receipt.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


# ---- agents ----

def _redacted(text: str | None, limit: int) -> str:
    if not text:
        return ""
    return redact_p3(text)[0][:limit]


def agent_runs(rt: Runtime, limit: int = 100) -> dict[str, Any]:
    conn = rt.store.conn
    runs = [
        {"id": r[0], "ts": r[1], "task_id": r[2], "agent": r[3] or "jarvis", "tool": r[4], "tier": r[5],
         "ok": bool(r[6]), "arguments": _redacted(r[7], 400), "result": _redacted(r[8], 300)}
        for r in conn.execute(
            """SELECT id, ts, task_id, agent, tool, tier, ok, arguments, result FROM tool_runs
               ORDER BY id DESC LIMIT ?""", (limit,))
    ]
    by_agent = [
        {"agent": r[0], "tool_runs": r[1], "failed": r[2], "last": r[3]}
        for r in conn.execute(
            """SELECT COALESCE(agent, 'jarvis'), COUNT(*), SUM(ok = 0), MAX(ts) FROM tool_runs
               GROUP BY COALESCE(agent, 'jarvis') ORDER BY MAX(ts) DESC""")
    ]
    by_route = [
        {"route": r[0], "calls": r[1], "input_tokens": r[2], "output_tokens": r[3],
         "notional_usd": round(r[4] or 0, 4), "last": r[5]}
        for r in conn.execute(
            """SELECT route, COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),
                      SUM(notional_usd), MAX(ts) FROM model_usage GROUP BY route ORDER BY MAX(ts) DESC""")
    ]
    return {"runs": runs, "by_agent": by_agent, "by_route": by_route, "events": audit_tail(rt.audit, 60)}


def audit_tail(audit: AuditLog, limit: int = 60, max_bytes: int = 262144) -> list[dict]:
    """Recent agent events (model calls, tool runs) from the audit log, newest first."""
    path: Path = audit.path
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    out = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") in ("model_call", "tool_run") and rec.get("agent"):
            rec.pop("arguments", None)  # arguments are in tool_runs (redacted there)
            out.append(rec)
            if len(out) >= limit:
                break
    return out


# ---- tools and the connector registry ----

def _build(rt: Runtime) -> ToolRegistry:
    reg = ToolRegistry(rt.store, rt.audit)
    return build_registry(reg, ToolDeps(
        home=rt.paths.home, store=rt.store, audit=rt.audit, memory=rt.memory, skills=rt.skills,
        session_id=lambda: "dashboard", max_privacy="P1", tools_config=rt.config.tools, web=WebClient(),
        quarantine=None, tavily_key=lambda: None, system=SystemTools(),
    ))


def tools_json(rt: Runtime) -> dict[str, Any]:
    builtin = _build(rt)
    path = registry_path(rt.paths.home)
    write_registry(builtin, path)  # creates the file or adds new tools; keeps Sachin's settings
    effective = _build(rt)
    apply_registry(effective, path, rt.audit)
    items = []
    for t in sorted(effective.all(), key=lambda t: (t.tier, t.spec.name)):
        base = builtin.get(t.spec.name)
        items.append({"name": t.spec.name, "description": t.spec.description, "tier": t.tier,
                      "builtin_tier": base.tier if base else t.tier, "enabled": t.enabled,
                      "taints": t.taints})
    return {"registry": str(path), "tools": items, "tiers": list(TIERS)}


class RegistryRefused(ValueError):
    pass


def edit_tool(rt: Runtime, name: str, tier: str | None, enabled: bool | None) -> dict[str, Any]:
    """Only safer changes: disable a tool or raise its tier. Lowering or re-enabling is refused
    here (edit the private registry file by hand for that), like apply_registry refuses lowering."""
    current = {t["name"]: t for t in tools_json(rt)["tools"]}
    tool = current.get(name)
    if not tool:
        raise KeyError(name)
    if tier is not None:
        if tier not in TIERS:
            raise RegistryRefused(f"unknown tier {tier}")
        if TIERS.index(tier) < TIERS.index(tool["tier"]):
            raise RegistryRefused(f"lowering {name} from {tool['tier']} to {tier} is not allowed from the dashboard")
    if enabled is True and not tool["enabled"]:
        raise RegistryRefused(f"re-enabling {name} is not allowed from the dashboard; edit the registry file")
    path = registry_path(rt.paths.home)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entry = data["connectors"]["builtin"]["tools"].setdefault(name, {"tier": tool["builtin_tier"], "enabled": True})
    old = dict(entry)
    if tier is not None:
        entry["tier"] = tier
    if enabled is False:
        entry["enabled"] = False
    path.write_text("# Jarvis connector and tool registry (private, not in git).\n"
                    "# You may set enabled: false or raise a tier. Lowering a tier is ignored.\n"
                    + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    rt.audit.write("registry_edit", source="dashboard", tool=name, before=old, after=dict(entry))
    return next(t for t in tools_json(rt)["tools"] if t["name"] == name)


# ---- usage ----

def usage_json(rt: Runtime, days: int = 30) -> dict[str, Any]:
    days = max(1, min(int(days), 366))
    rows = rt.store.conn.execute(
        """SELECT date(ts), route, provider, model, COUNT(*), COALESCE(SUM(input_tokens),0),
                  COALESCE(SUM(output_tokens),0), SUM(notional_usd), SUM(cost_usd)
           FROM model_usage WHERE ts >= datetime('now', ?)
           GROUP BY date(ts), route, provider, model ORDER BY date(ts) DESC, route""",
        (f"-{days} days",)).fetchall()
    items = [{"day": r[0], "route": r[1], "provider": r[2], "model": r[3], "calls": r[4], "input_tokens": r[5],
              "output_tokens": r[6], "notional_usd": round(r[7] or 0, 4), "billed_usd": round(r[8] or 0, 4)}
             for r in rows]
    per_day: dict[str, dict[str, float]] = {}
    for it in items:
        d = per_day.setdefault(it["day"], {"calls": 0, "notional_usd": 0.0, "billed_usd": 0.0, "tokens": 0})
        d["calls"] += it["calls"]
        d["notional_usd"] = round(d["notional_usd"] + it["notional_usd"], 4)
        d["billed_usd"] = round(d["billed_usd"] + it["billed_usd"], 4)
        d["tokens"] += it["input_tokens"] + it["output_tokens"]
    totals = {"calls": sum(i["calls"] for i in items),
              "notional_usd": round(sum(i["notional_usd"] for i in items), 4),
              "billed_usd": round(sum(i["billed_usd"] for i in items), 4),
              "input_tokens": sum(i["input_tokens"] for i in items),
              "output_tokens": sum(i["output_tokens"] for i in items)}
    return {"days": days, "items": items,
            "per_day": [{"day": k, **v} for k, v in sorted(per_day.items(), reverse=True)], "totals": totals}


def routes_json(rt: Runtime) -> list[dict[str, Any]]:
    out = []
    for name, spec in (rt.config.routing.get("routes") or {}).items():
        cands = spec.get("candidates") or []
        first = cands[0] if cands else {}
        out.append({"route": name, "provider": first.get("provider"), "model": first.get("model"),
                    "effort": first.get("effort"), "max_privacy": spec.get("max_privacy")})
    return out
