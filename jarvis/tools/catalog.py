"""All built-in tools with their risk tiers, plus the connector registry file.

The registry file (<home>/connectors/registry.yaml, private) lists every tool. Sachin may
disable a tool or raise its tier there; lowering a tier below the built-in one is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import yaml

from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.privacy import SENSITIVITY_TO_CLASS, allowed
from jarvis.providers.base import ToolSpec
from jarvis.skills.loader import SkillLibrary
from jarvis.tools.files import FileTools, PathPolicy
from jarvis.tools.quarantine import Quarantine
from jarvis.tools.registry import TIERS, Tool, ToolRegistry
from jarvis.tools.system import MEDIA_ACTIONS, SystemTools
from jarvis.tools.web import WebClient, WebError, format_results, format_weather


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}


@dataclass
class ToolDeps:
    home: Path
    store: Store
    audit: AuditLog
    memory: MemoryStore | None
    skills: SkillLibrary | None
    session_id: Callable[[], str]
    max_privacy: str
    tools_config: dict
    web: WebClient
    quarantine: Quarantine | None
    tavily_key: Callable[[], str | None]
    system: SystemTools


def file_roots(home: Path, tools_config: dict) -> list[Path]:
    roots = []
    for raw in (tools_config.get("files") or {}).get("allowed") or ["workspace"]:
        p = Path(raw).expanduser()
        roots.append(p if p.is_absolute() else home / p)
    return roots


def build_registry(reg: ToolRegistry, d: ToolDeps) -> ToolRegistry:
    add = reg.register

    # ---- memory, sessions, skills (T0) ----
    if d.memory:
        mem = d.memory

        def memory_search(args: dict) -> str:
            lines = []
            for hit in mem.search(args["query"], k=5):
                m = hit.memory
                if not allowed(SENSITIVITY_TO_CLASS.get(m.sensitivity, "P2"), d.max_privacy):
                    lines.append(f"- [{m.id}] (sensitive memory withheld)")
                    continue
                mem.mark_used(m.id)
                lines.append(f"- [{m.id}, {m.type}] {m.summary_en or m.name}: {m.body}")
            return "\n".join(lines) or "No matching memories."

        add(Tool(ToolSpec("memory_search", "Search the user's long-term memory. Use English keywords and the user's own words.",
                          _obj({"query": S}, ["query"])), "T0", memory_search))

    def session_search(args: dict) -> str:
        rows = d.store.search_sessions(args["query"], limit=5, exclude_session=d.session_id())
        return "\n".join(f"- {r['ts']} {r['role']}: {r['text'][:300]}" for r in rows) or "No matching past conversations."

    add(Tool(ToolSpec("session_search", "Search past conversations with the user.", _obj({"query": S}, ["query"])),
             "T0", session_search))

    if d.skills:
        skills = d.skills
        add(Tool(ToolSpec("load_skill", "Load the full instructions of a skill from the skill index.",
                          _obj({"name": S}, ["name"])), "T0",
                 lambda a: skills.load(a["name"]) or f"No skill named {a['name']}."))

    # ---- files ----
    policy = PathPolicy(file_roots(d.home, d.tools_config))
    files = FileTools(policy)

    def paths(*keys: str) -> Callable[[dict], None]:
        def check(args: dict) -> None:
            for k in keys:
                if k in args and args[k]:
                    policy.resolve(args[k])
        return check

    where = "Paths are relative to the Jarvis workspace folder."
    add(Tool(ToolSpec("read_file", f"Read a text file. {where}", _obj({"path": S}, ["path"])),
             "T0", files.read_file, precheck=paths("path")))
    add(Tool(ToolSpec("list_folder", f"List a folder. {where} Empty path = the workspace.", _obj({"path": S}, [])),
             "T0", files.list_folder, precheck=paths("path")))
    add(Tool(ToolSpec("write_file", f"Create a NEW text file (fails if it exists). {where}",
                      _obj({"path": S, "content": S}, ["path", "content"])),
             "T1", files.write_file, verify=files.verify_write, precheck=paths("path")))
    add(Tool(ToolSpec("overwrite_file", f"Replace the content of an existing file; the old version is kept. {where}",
                      _obj({"path": S, "content": S}, ["path", "content"])),
             "T2", files.overwrite_file, verify=files.verify_write, precheck=paths("path")))
    add(Tool(ToolSpec("move_file", f"Move or rename a file. End destination with / to move into a folder. {where}",
                      _obj({"source": S, "destination": S}, ["source", "destination"])),
             "T2", files.move_file, verify=files.verify_move, precheck=paths("source", "destination")))
    add(Tool(ToolSpec("delete_file", f"Delete a file (kept in the workspace trash). {where}", _obj({"path": S}, ["path"])),
             "T3", files.delete_file, verify=files.verify_delete, precheck=paths("path")))

    # ---- web (output is untrusted: taints the session) ----
    def web_search(args: dict) -> str:
        key = d.tavily_key()
        if not key:
            return "Web search is not set up: the Tavily key is missing (jarvis secret set tavily_api_key)."
        topic = args.get("topic") or "general"
        try:
            return format_results(d.web.tavily_search(key, args["query"], topic=topic, max_results=5))
        except WebError as e:
            return f"Web search failed: {e}"

    add(Tool(ToolSpec("web_search", "Search the web (Tavily). Use topic 'news' for recent news, including cricket.",
                      _obj({"query": S, "topic": {"type": "string", "enum": ["general", "news", "finance"]}}, ["query"])),
             "T0", web_search, taints=True))

    def web_fetch(args: dict) -> str:
        if not d.quarantine:
            return "Reading web pages is not available."
        try:
            text = d.web.fetch_text(args["url"])
        except WebError as e:
            return f"Could not fetch the page: {e}"
        return d.quarantine.extract(text, args["question"], args["url"])

    add(Tool(ToolSpec("web_fetch", "Read one web page and answer a question from it. Only use links the user gave "
                      "or that came from web_search.", _obj({"url": S, "question": S}, ["url", "question"])),
             "T0", web_fetch, taints=True))

    default_place = (d.tools_config.get("weather") or {}).get("default_place", "")

    def weather(args: dict) -> str:
        place = args.get("place") or default_place
        if not place:
            return "Which place? (No default place is set.)"
        try:
            return format_weather(d.web.weather(place, int(args.get("days") or 3)))
        except WebError as e:
            return f"Weather failed: {e}"

    add(Tool(ToolSpec("weather", "Current weather and forecast for a place (Open-Meteo).",
                      _obj({"place": S, "days": {"type": "integer", "description": "1 to 7"}}, [])),
             "T0", weather))

    # ---- computer and media ----
    sysd = d.system
    add(Tool(ToolSpec("open_app", f"Open an allowed app: {', '.join(sysd.app_names())}.",
                      _obj({"name": {"type": "string", "enum": sysd.app_names()}}, ["name"])),
             "T1", sysd.open_app, verify=sysd.verify_open_app))
    add(Tool(ToolSpec("notify", "Show a desktop notification to the user.",
                      _obj({"message": S, "title": S}, ["message"])), "T1", sysd.notify))
    add(Tool(ToolSpec("media", "Media and volume keys. times = how many volume steps (1-10).",
                      _obj({"action": {"type": "string", "enum": list(MEDIA_ACTIONS)}, "times": {"type": "integer"}},
                           ["action"])), "T1", sysd.media))
    add(Tool(ToolSpec("open_url", "Open a link in the user's browser.", _obj({"url": S}, ["url"])), "T2", sysd.open_url))
    add(Tool(ToolSpec("set_brightness", "Set screen brightness, 0 to 100.",
                      _obj({"level": {"type": "integer"}}, ["level"])), "T2", sysd.brightness))
    return reg


# ---- connector registry file ----

def registry_path(home: Path) -> Path:
    return home / "connectors" / "registry.yaml"


def write_registry(reg: ToolRegistry, path: Path) -> None:
    """Create the file if missing; add new tools; keep Sachin's settings for existing ones."""
    existing = _read(path)
    tools = existing.setdefault("connectors", {}).setdefault("builtin", {"type": "native", "tools": {}})
    tools.setdefault("type", "native")
    entries = tools.setdefault("tools", {})
    for t in reg.all():
        entries.setdefault(t.spec.name, {"tier": t.tier, "enabled": True})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Jarvis connector and tool registry (private, not in git).\n"
                    "# You may set enabled: false or raise a tier. Lowering a tier is ignored.\n"
                    + yaml.safe_dump(existing, sort_keys=False, allow_unicode=True), encoding="utf-8")


def apply_registry(reg: ToolRegistry, path: Path, audit: AuditLog) -> None:
    entries = (((_read(path).get("connectors") or {}).get("builtin") or {}).get("tools")) or {}
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


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}
