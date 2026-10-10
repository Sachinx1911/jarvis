"""SKILL.md skills (open standard). Only names and descriptions go into the prompt;
the full skill is loaded on demand with the load_skill tool.

Learned skills live in <home>/skills/<name>/SKILL.md (git-ignored).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path


class SkillLibrary:
    def __init__(self, root: Path):
        self.root = root

    def index(self) -> list[SkillInfo]:
        out: list[SkillInfo] = []
        if not self.root.exists():
            return out
        for path in sorted(self.root.glob("*/SKILL.md")):
            meta = self._frontmatter(path.read_text(encoding="utf-8"))
            name = str(meta.get("name") or path.parent.name)
            out.append(SkillInfo(name, str(meta.get("description", "")).strip(), path))
        return out

    def load(self, name: str) -> str | None:
        for info in self.index():
            if info.name == name:  # only known skills: no paths from the model
                return info.path.read_text(encoding="utf-8")
        return None

    @staticmethod
    def _frontmatter(text: str) -> dict:
        m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
        if not m:
            return {}
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}
