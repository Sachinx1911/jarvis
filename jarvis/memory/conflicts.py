"""Possible memory conflicts: active memories about the same subject that say different things.

Research rule (PLAN.md, write path): conflicts are only judged on the same subject, and an old
memory is superseded, never deleted. This check only lists candidates; Sachin decides
(`jarvis memory conflicts`, then supersede or archive). No model is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.memory.model import Memory

CHECKED_TYPES = ("fact", "preference", "procedure", "constraint")


@dataclass
class Conflict:
    subject: str
    type: str
    memories: list[Memory]

    def line(self) -> str:
        ids = ", ".join(m.id for m in self.memories)
        return f"{self.subject} ({self.type}): {ids}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def find_conflicts(memories: list[Memory]) -> list[Conflict]:
    groups: dict[tuple[str, str], list[Memory]] = {}
    for m in memories:
        if m.status != "active" or m.type not in CHECKED_TYPES or not m.subject.strip():
            continue
        groups.setdefault((_norm(m.subject), m.type), []).append(m)
    out = []
    for (subject, mtype), mems in sorted(groups.items()):
        if len(mems) > 1 and len({_norm(m.body) for m in mems}) > 1:
            out.append(Conflict(mems[0].subject.strip(), mtype, sorted(mems, key=lambda m: m.id)))
    return out
