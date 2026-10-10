"""Core memory: two small curated files that are in every prompt (idea from Hermes Agent).

- profile/USER.md: who the user is and how they like to work (preferences, communication style,
  habits). Hermes calls this the user profile.
- profile/MEMORY.md: Jarvis's own notes: important facts, conventions, lessons learned, the
  active project context.

Not to be confused with memory/MEMORY.md, the auto-generated index of the long-term memory files
(jarvis/memory/store.py). The long-term memory stays the main store; core memory holds the few
things that should be present in every reply without a search.

Rules (checked against https://github.com/NousResearch/hermes-agent docs, "Persistent Memory",
2026-10-11, and adapted to Jarvis):
- Bounded on purpose (Hermes: 1,375 and 2,200 characters) so the prompt stays small. A write that
  would overflow is refused; Jarvis must merge or remove entries first. No silent dropping.
- Entries are separated by a line holding only "§". add / replace / remove; replace and remove
  find the entry by a short unique piece of its text.
- Exact duplicates are not added.
- Every entry goes to the cloud model with every message, so only P0/P1 text is accepted: P3
  (ID numbers, OTPs, card numbers, keys) and sensitive topics (health, money, ID documents, other
  people's contact details) are refused; those belong in /remember-private, which stays local.
- Entries are scanned before saving for prompt-injection phrases and invisible characters,
  because they are injected into the system prompt.
- Every change is written to the audit log (action, target, sizes), never the text itself.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.memory.sensitivity import sensitive_categories
from jarvis.privacy import find_p3

SEP = "\n§\n"
TARGETS = ("user", "memory")
TITLES = {"user": "USER PROFILE (who the user is, how they like to work)",
          "memory": "JARVIS NOTES (important facts, conventions, lessons, active project)"}
FILES = {"user": "USER.md", "memory": "MEMORY.md"}
DEFAULT_LIMITS = {"user": 1375, "memory": 2200}

# Zero-width and bidirectional control characters: invisible text can hide instructions.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|messages)"
    r"|disregard (all |any |the )?(previous|prior|above|your) (instructions|rules)"
    r"|(reveal|print|show|repeat) (the |your )?(system prompt|hidden instructions)"
    r"|you are now (a |an |in )|new instructions:|developer mode|jailbreak"
    r"|(send|post|upload|forward|exfiltrate)\b.{0,40}\b(to|at) (https?://|\w+@\w+)"
    r"|curl\s+-|wget\s+http|ssh-(rsa|ed25519) |-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|(api[_ -]?key|password|passcode|secret[_ -]?key)\s*[:=]",
    re.IGNORECASE,
)


class CoreMemoryError(ValueError):
    """A write was refused; the message says why and what to do instead."""


@dataclass
class CoreMemory:
    home: Path
    limits: dict[str, int] | None = None

    def __post_init__(self):
        self.limits = {**DEFAULT_LIMITS, **(self.limits or {})}

    def path(self, target: str) -> Path:
        return self.home / "profile" / FILES[self._target(target)]

    @staticmethod
    def _target(target: str) -> str:
        if target not in TARGETS:
            raise CoreMemoryError(f"target must be one of {', '.join(TARGETS)}, not {target!r}")
        return target

    def entries(self, target: str) -> list[str]:
        p = self.path(target)
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
        return [e.strip() for e in re.split(r"\n\s*§\s*\n", "\n" + text + "\n") if e.strip()]

    def used(self, target: str) -> int:
        return len(SEP.join(self.entries(target)))

    def _save(self, target: str, entries: list[str]) -> None:
        p = self.path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        body = SEP.join(entries)
        p.write_text(body + ("\n" if body else ""), encoding="utf-8")

    # ---- checks ----

    @staticmethod
    def check_text(content: str) -> str:
        """The cleaned entry, or CoreMemoryError when it must not go into every prompt."""
        text = unicodedata.normalize("NFC", content or "").strip()
        if not text:
            raise CoreMemoryError("the entry is empty")
        if "§" in text:
            raise CoreMemoryError("the entry must not contain the § separator")
        if _INVISIBLE.search(text):
            raise CoreMemoryError("the entry contains invisible characters; write it in plain text")
        if _INJECTION.search(text):
            raise CoreMemoryError("the entry looks like an instruction to override rules or send data; not saved")
        if find_p3(text):
            raise CoreMemoryError("the entry holds secret data (an ID number, OTP, card number or key); "
                                  "never put that in core memory")
        cats = sensitive_categories(text)
        if cats:
            raise CoreMemoryError(f"the entry is sensitive ({', '.join(sorted(cats))}); core memory goes to the "
                                  "cloud model with every message, so save it with /remember-private instead")
        return text

    def _fits(self, target: str, entries: list[str]) -> None:
        size, limit = len(SEP.join(entries)), self.limits[target]
        if size > limit:
            raise CoreMemoryError(f"{FILES[target]} would hold {size} of {limit} characters. Merge or remove "
                                  "entries first (replace two related entries with one shorter one), then try again")

    def _find(self, entries: list[str], old_text: str) -> int:
        needle = (old_text or "").strip()
        if not needle:
            raise CoreMemoryError("old_text is empty: give a short unique piece of the entry")
        exact = [i for i, e in enumerate(entries) if e == needle]
        if exact:
            return exact[0]
        hits = [i for i, e in enumerate(entries) if needle.lower() in e.lower()]
        if not hits:
            raise CoreMemoryError(f"no entry contains {needle!r}")
        if len(hits) > 1:
            raise CoreMemoryError(f"{len(hits)} entries contain {needle!r}; give a longer, unique piece")
        return hits[0]

    # ---- changes ----

    def add(self, target: str, content: str) -> str:
        target = self._target(target)
        text = self.check_text(content)
        entries = self.entries(target)
        if any(" ".join(e.split()) == " ".join(text.split()) for e in entries):
            return f"Already in {FILES[target]}; no duplicate added."
        self._fits(target, entries + [text])
        self._save(target, entries + [text])
        return f"Saved to {FILES[target]} ({self.used(target)}/{self.limits[target]} characters)."

    def replace(self, target: str, old_text: str, content: str) -> str:
        target = self._target(target)
        text = self.check_text(content)
        entries = self.entries(target)
        i = self._find(entries, old_text)
        new = entries[:i] + [text] + entries[i + 1:]
        self._fits(target, new)
        self._save(target, new)
        return f"Updated an entry in {FILES[target]} ({self.used(target)}/{self.limits[target]} characters)."

    def remove(self, target: str, old_text: str) -> str:
        target = self._target(target)
        entries = self.entries(target)
        i = self._find(entries, old_text)
        self._save(target, entries[:i] + entries[i + 1:])
        return f"Removed an entry from {FILES[target]} ({self.used(target)}/{self.limits[target]} characters)."

    def set_all(self, target: str, text: str) -> str:
        """The user edits the whole file (dashboard): every entry is checked the same way."""
        target = self._target(target)
        raw = [e.strip() for e in re.split(r"\n\s*§\s*\n", "\n" + (text or "").replace("\r\n", "\n") + "\n")]
        entries = [self.check_text(e) for e in raw if e]
        self._fits(target, entries)
        self._save(target, entries)
        return f"Saved {FILES[target]} ({self.used(target)}/{self.limits[target]} characters)."

    # ---- prompt ----

    def block(self) -> str:
        """The core-memory section of the system prompt ("" when both files are empty)."""
        parts = []
        for target in TARGETS:
            entries = self.entries(target)
            if not entries:
                continue
            used, limit = self.used(target), self.limits[target]
            parts.append(f"### {TITLES[target]} [{round(100 * used / limit)}% - {used}/{limit} chars]\n"
                         + SEP.join(entries))
        if not parts:
            return ""
        return ("## Core memory (always here; curated; change it with the core_memory tool)\n"
                + "\n\n".join(parts))

    def status(self) -> dict[str, Any]:
        return {t: {"file": f"profile/{FILES[t]}", "entries": self.entries(t), "used": self.used(t),
                    "limit": self.limits[t]} for t in TARGETS}


def core_settings(settings: dict[str, Any]) -> dict[str, Any]:
    c = {"enabled": True, "user_chars": DEFAULT_LIMITS["user"], "memory_chars": DEFAULT_LIMITS["memory"],
         "write_approval": False}
    c.update((settings or {}).get("core", {}) or {})
    return c


def core_from_settings(home: Path, settings: dict[str, Any]) -> CoreMemory | None:
    c = core_settings(settings)
    if not c["enabled"]:
        return None
    return CoreMemory(home, {"user": int(c["user_chars"]), "memory": int(c["memory_chars"])})
