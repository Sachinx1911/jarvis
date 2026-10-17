"""Context builder: what goes into the system prompt for one turn.

Order keeps the stable parts first (good for prompt caching): personality, rules,
memory index, hard rules, skill index; then per-turn memories and the local time.
Memories above the route's privacy limit are withheld and counted, never sent.

Per-turn retrieval (research 2026-10-10, topic 4): structured memories plus 1-3 short raw
excerpts from past chats (session search), in separate labelled blocks. Raw excerpts keep
exact words, numbers and dates that extraction drops; the memories stay the main source.
The question's date range (if any) is applied to both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jarvis.memory import session_facts
from jarvis.memory.store import MemoryStore, SearchHit
from jarvis.memory.timefilter import extract_range
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import SENSITIVITY_TO_CLASS, allowed, find_p3, redact_p3
from jarvis.skills.loader import SkillLibrary

MAX_RETRIEVED = 5
MAX_EXCERPTS = 3
EXCERPT_CHARS = 300          # one excerpt
EXCERPTS_BUDGET = 900        # all excerpts together
CHAT_TEXT_CLASS = "P1"       # past chat lines are the user's normal conversation


@dataclass
class RetrievalOptions:
    """Switches for the retrieval improvements, so the memory eval can measure each one."""
    time_aware: bool = True       # date range from the question boosts memories and messages
    session_facts: bool = True    # session search also matches extracted facts
    excerpts: bool = True         # raw past-chat excerpts next to the memories


@dataclass
class BuiltContext:
    system: str
    memory_ids: list[str] = field(default_factory=list)
    withheld: int = 0
    excerpt_ids: list[int] = field(default_factory=list)   # message ids of the past-chat excerpts


def soul_text(home: Path) -> str:
    own = home / "profile" / "SOUL.md"
    path = own if own.exists() else PROMPTS_DIR / "SOUL.example.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.startswith("Copied to profile/")).strip()


class ContextBuilder:
    def __init__(self, home: Path, memory: MemoryStore | None, skills: SkillLibrary | None, max_privacy: str = "P1",
                 docs=None):
        self.home = home
        self.memory = memory
        self.skills = skills
        self.max_privacy = max_privacy
        self.docs = docs          # DocLibrary; searched only while a project is active
        self.project: str | None = None
        self.workspace: str = "personal"   # the office this chat works in (PLAN.md 18.2 step 0)
        self.share_personal: bool = True   # personal memories visible here (a company may say no)
        self.options = RetrievalOptions()
        self.session_id: str | None = None   # the chat in progress; guessed from the newest message if unset

    def _ok(self, sensitivity: str) -> bool:
        return allowed(SENSITIVITY_TO_CLASS.get(sensitivity, "P2"), self.max_privacy)

    def retrieve(self, user_text: str, now: datetime, k: int = MAX_RETRIEVED,
                 excerpts: int = MAX_EXCERPTS) -> tuple[list[SearchHit], list[session_facts.SessionHit]]:
        """Memories and past-chat messages for one message, best first, before privacy checks."""
        if not self.memory or not user_text.strip():
            return [], []
        rng = extract_range(user_text, now.date()) if self.options.time_aware and self.memory.time_aware else None
        scope = f"project:{self.project}" if self.project else None
        hits = self.memory.search(user_text, k=k, scope=scope, time_range=rng,
                                  workspace=self.workspace, share_personal=self.share_personal)
        if not self.options.excerpts or excerpts <= 0:
            return hits, []
        conn = self.memory.db
        current = self.session_id or session_facts.latest_session(conn, user_text)
        found = session_facts.search(
            conn, user_text, limit=excerpts, exclude_session=current, time_range=rng,
            use_facts=self.options.session_facts, script_forms=self.memory.script_forms,
            time_aware=self.options.time_aware and self.memory.time_aware,
            support_memory_ids=[h.memory.id for h in hits])
        return hits, found

    def _excerpt_block(self, found: list[session_facts.SessionHit], ctx: BuiltContext) -> str:
        """Past-chat excerpts within the size budget. Lines that quote a memory this route may
        not see are dropped; secrets are redacted (they should never be there anyway)."""
        if not found or not allowed(CHAT_TEXT_CLASS, self.max_privacy):
            return ""
        mem = self.memory
        assert mem is not None
        hidden = []
        for mid, sensitivity in mem.db.execute("SELECT id, sensitivity FROM memory_index"):
            if not self._ok(sensitivity):
                m = mem.get(mid)
                if m and m.evidence:
                    hidden.append(m.evidence.lower())
        lines, used = [], 0
        for hit in found:
            low = hit.text.lower()
            if any(q and q in low for part in hidden for q in part.split(" | ")):
                ctx.withheld += 1
                continue
            text = " ".join(hit.text.split())
            if find_p3(text):
                text, _ = redact_p3(text)
            if len(text) > EXCERPT_CHARS:
                text = text[:EXCERPT_CHARS - 3].rstrip() + "..."
            if used + len(text) > EXCERPTS_BUDGET:
                break
            used += len(text)
            line = f"- [{hit.ts[:10]}, {hit.role}] {text}"
            if hit.superseded:
                line += f" (OUTDATED: {', '.join(hit.superseded)} was replaced by a newer memory)"
            elif hit.memory_ids:
                line += f" (source of {', '.join(hit.memory_ids)})"
            lines.append(line)
            ctx.excerpt_ids.append(hit.message_id)
        if not lines:
            return ""
        return ("## Past chat excerpts (raw words from earlier chats; may be outdated)\n" + "\n".join(lines))

    def build(self, user_text: str, now: datetime) -> BuiltContext:
        ctx = BuiltContext(system="")
        parts = [soul_text(self.home), (PROMPTS_DIR / "jarvis_system.md").read_text(encoding="utf-8").strip()]

        # Core memory (profile/USER.md + profile/MEMORY.md): only P0/P1 text is ever saved there.
        if allowed("P1", self.max_privacy):
            from jarvis.memory.core import core_from_settings
            from jarvis.memory.upkeep_settings import load_memory_settings

            core = core_from_settings(self.home, load_memory_settings())
            if core:
                parts.append(core.block())

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
            hits, found = self.retrieve(user_text, now)
            for hit in hits:
                m = hit.memory
                if m.type == "constraint":
                    continue  # already included above
                if not self._ok(m.sensitivity):
                    ctx.withheld += 1
                    continue
                saved = f", saved {m.valid_from}" if m.valid_from else ""
                lines.append(f"- [{m.id}, {m.type}{saved}] {m.summary_en or m.name}\n  {m.body}")
                ctx.memory_ids.append(m.id)
            if lines:
                parts.append("## Memories relevant to this message\n" + "\n".join(lines))
            block = self._excerpt_block(found, ctx)
            if block:
                parts.append(block)

        if self.docs is not None and self.project and user_text.strip():
            from jarvis.docs.tools import doc_context

            section, withheld = doc_context(self.docs, user_text, self.project, self.max_privacy)
            if section:
                parts.append(section)
            ctx.withheld += withheld

        if ctx.withheld:
            parts.append(f"Note: {ctx.withheld} sensitive memories or private document parts were withheld from you for privacy. "
                         "If the answer may depend on them, tell the user it was withheld.")
        parts.append(f"Local time: {now.strftime('%Y-%m-%d %H:%M')}")
        ctx.system = "\n\n".join(p for p in parts if p)
        return ctx
