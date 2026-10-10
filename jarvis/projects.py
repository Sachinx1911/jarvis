"""Project workspace (PLAN.md section 7): one folder per project, shared by every agent.

projects/<name>/PROJECT.md (goal, status, people, links, rules), docs/ (approved documents),
notes/, outputs/ (finished results, copied there by Jarvis after verification).
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = """# {name}

## Goal
{goal}

## Status
Started.

## People

## Links

## Project rules
"""
MAX_CONTEXT_CHARS = 4000


def valid_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("project name needs letters or digits")
    return slug[:40]


class ProjectStore:
    def __init__(self, home: Path):
        self.root = home / "projects"

    def create(self, name: str, goal: str = "") -> Path:
        slug = valid_name(name)
        path = self.root / slug
        for sub in ("docs", "notes", "outputs"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        md = path / "PROJECT.md"
        if not md.exists():
            md.write_text(TEMPLATE.format(name=slug, goal=goal or "(not set)"), encoding="utf-8")
        return path

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "PROJECT.md").exists())

    def exists(self, name: str) -> bool:
        return (self.root / valid_name(name) / "PROJECT.md").exists()

    def context(self, name: str) -> str:
        """PROJECT.md for agents' context packs (read-only)."""
        md = self.root / valid_name(name) / "PROJECT.md"
        return md.read_text(encoding="utf-8")[:MAX_CONTEXT_CHARS] if md.exists() else ""

    def outputs(self, name: str) -> Path:
        path = self.root / valid_name(name) / "outputs"
        path.mkdir(parents=True, exist_ok=True)
        return path
