"""Context builder: what goes into the system prompt for one turn.

Order keeps the stable parts first (good for prompt caching): personality, rules,
memory index, hard rules, skill index; then per-turn memories and the local time.
Memories above the route's privacy limit are withheld and counted, never sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jarvis.memory.store import MemoryStore
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import SENSITIVITY_TO_CLASS, allowed
from jarvis.skills.loader import SkillLibrary

MAX_RETRIEVED = 5


@dataclass
class BuiltContext:
    system: str
    memory_ids: list[str] = field(default_factory=list)
    withheld: int = 0


def soul_text(home: Path) -> str:
    own = home / "profile" / "SOUL.md"
    path = own if own.exists() else PROMPTS_DIR / "SOUL.example.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.startswith("Copied to profile/")).strip()


class ContextBuilder:
    def __init__(self, home: Path, memory: MemoryStore | None, skills: SkillLibrary | None, max_privacy: str = "P1"):
        self.home = home
        self.memory = memory
        self.skills = skills
        self.max_privacy = max_privacy

    def _ok(self, sensitivity: str) -> bool:
        return allowed(SENSITIVITY_TO_CLASS.get(sensitivity, "P2"), self.max_privacy)

    def build(self, user_text: str, now: datetime) -> BuiltContext:
        ctx = BuiltContext(system="")
        parts = [soul_text(self.home), (PROMPTS_DIR / "jarvis_system.md").read_text(encoding="utf-8").strip()]

        if self.memory:
            index = (self.memory.root / "MEMORY.md")
            if index.exists():
                parts.append("## Memory index\n" + index.read_text(encoding="utf-8").replace("# Memory index", "").strip())

            rules = []
            for m in self.memory.list(type="constraint"):
                if self._ok(m.sensitivity):
                    rules.append(f"- {m.summary_en or m.name}: {m.body}")
                else:
                    ctx.withheld += 1
            if rules:
                parts.append("## Hard rules (always follow)\n" + "\n".join(rules))

        if self.skills:
            skills = self.skills.index()
            if skills:
                parts.append("## Skills (load one with load_skill before using it)\n"
                             + "\n".join(f"- {s.name}: {s.description}" for s in skills))

        if self.memory and user_text.strip():
            lines = []
            for hit in self.memory.search(user_text, k=MAX_RETRIEVED):
                m = hit.memory
                if m.type == "constraint":
                    continue  # already included above
                if not self._ok(m.sensitivity):
                    ctx.withheld += 1
                    continue
                lines.append(f"- [{m.id}, {m.type}] {m.summary_en or m.name}\n  {m.body}")
                ctx.memory_ids.append(m.id)
            if lines:
                parts.append("## Memories relevant to this message\n" + "\n".join(lines))

        if ctx.withheld:
            parts.append(f"Note: {ctx.withheld} sensitive memories were withheld from you for privacy. "
                         "If the answer may depend on them, tell the user it was withheld.")
        parts.append(f"Local time: {now.strftime('%Y-%m-%d %H:%M')}")
        ctx.system = "\n\n".join(p for p in parts if p)
        return ctx
