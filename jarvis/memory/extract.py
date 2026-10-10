"""Memory write path (PLAN.md 6.3).

- remember(): the user said "remember this". Saved immediately with their words as
  evidence; a structured model call adds an English summary and keywords.
- extract_session(): two-step extraction from a finished conversation. The model sees
  only the user's messages, every candidate needs an exact quote, and similar memories
  decide ADD / UPDATE / SUPERSEDE / NOOP / REJECT. Old memories are superseded, never
  deleted.

Every memory built from model output also goes through the deterministic sensitivity
check (jarvis.memory.sensitivity), which can only raise it to "sensitive".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jarvis.control.audit import AuditLog
from jarvis.memory.model import Memory
from jarvis.memory.sensitivity import inherit_sensitive, raise_sensitivity, sensitive_categories
from jarvis.memory.store import MemoryRejected, MemoryStore
from jarvis.memory.translit import add_script_forms
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import SENSITIVITY_TO_CLASS, find_p3
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.schema import validate as _valid

ROUTE = "memory_extractor"
MAX_SIMILAR = 10
PRIVATE_DUPLICATE = 0.9   # trigram similarity at or above this to a private memory = already known


def _private(m: Memory) -> bool:
    """Sensitive (P2) memories never go to the memory_extractor route, which allows P1 only."""
    return SENSITIVITY_TO_CLASS.get(m.sensitivity, "P2") not in ("P0", "P1")


def _text_of(m: Memory) -> str:
    return m.body.strip() or m.summary_en.strip() or m.name

_FIELDS: dict[str, Any] = {
    "name": {"type": "string"},
    "type": {"type": "string", "enum": ["fact", "preference", "procedure", "constraint"]},
    "subject": {"type": "string"},
    "summary_en": {"type": "string"},
    "keywords": {"type": "string"},
    "when_to_use": {"type": "string"},
    "sensitivity": {"type": "string", "enum": ["normal", "sensitive"]},
}
ENRICH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": _FIELDS,
    "required": list(_FIELDS),
    "additionalProperties": False,
}
_CANDIDATE = {
    "type": "object",
    "properties": {
        **_FIELDS,
        "evidence": {"type": "string"},
        "source": {"type": "string", "enum": ["user-said", "inferred"]},
        "body": {"type": "string"},
    },
    "required": [*_FIELDS, "evidence", "source", "body"],
    "additionalProperties": False,
}
EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"candidates": {"type": "array", "items": _CANDIDATE}},
    "required": ["candidates"],
    "additionalProperties": False,
}
DECIDE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["ADD", "UPDATE", "SUPERSEDE", "NOOP", "REJECT"]},
        "target_id": {"type": "string"},
    },
    "required": ["action", "target_id"],
    "additionalProperties": False,
}


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _marathi_words(text: str, limit: int = 8) -> str:
    """Devanagari words of a note (3+ letters), so their romanized keys reach the keywords
    even when no model enriched the note."""
    from jarvis.memory.translit import is_devanagari, words

    out = [w for w in words(text) if is_devanagari(w) and len(w) >= 3]
    return " ".join(list(dict.fromkeys(out))[:limit])


class Extractor:
    def __init__(self, store: MemoryStore, provider: ReasoningProvider | None,
                 decision: RouteDecision | None, audit: AuditLog):
        self.store = store
        self.provider = provider
        self.decision = decision
        self.audit = audit

    def _structured(self, system: str, user_text: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.provider or not self.decision:
            return None
        req = LLMRequest(
            route=ROUTE, model=self.decision.model, system=system,
            messages=[Message.text("user", user_text)], reasoning=self.decision.effort,  # type: ignore[arg-type]
            response_schema=schema, privacy_classes=frozenset({"P1"}),
        )
        try:
            res = self.provider.structured(req, schema)
        except (ProviderError, NotImplementedError) as e:
            self.audit.write("extractor_error", route=ROUTE, detail=str(e))
            return None
        self.audit.write("model_call", route=ROUTE, provider=res.response.provider, model=res.response.model,
                         input_tokens=res.response.usage.input_tokens, output_tokens=res.response.usage.output_tokens,
                         valid=res.valid)
        if not res.valid or not _valid(res.data, schema):
            self.audit.write("extractor_invalid_output", route=ROUTE)
            return None
        return res.data

    # ---- explicit "remember this" ----

    def remember(self, text: str, private: bool = False) -> Memory:
        text = text.strip()
        if not text:
            raise MemoryRejected("nothing to remember")
        if find_p3(text):
            raise MemoryRejected("looks like a password, key, OTP or ID number; never stored")
        mem = Memory(name=text[:48], body=text, evidence=text, source="user-said", confidence="high")
        auto = sensitive_categories(text)
        if private or auto:
            # Stays local: not sent for enrichment (the memory_extractor route allows P1 only).
            mem.sensitivity = "sensitive"
        else:
            data = self._structured(_prompt("memory_enrich.md"), text, ENRICH_SCHEMA)
            if data:
                for k in _FIELDS:
                    setattr(mem, k, data[k])
        # Both scripts in the keywords, whatever the model wrote (Devanagari <-> romanized).
        mem.keywords = add_script_forms(f"{mem.keywords} {_marathi_words(text)}".strip(), mem.summary_en)
        auto = auto or raise_sensitivity(mem)  # the model's summary and keywords are checked too
        saved = self.store.save(mem)
        self.audit.write("memory_saved", id=saved.id, type=saved.type, how="remember", enriched=bool(saved.summary_en),
                         auto_sensitive=auto)
        return saved

    # ---- extraction from a conversation ----

    def extract_session(self, user_messages: list[str]) -> list[tuple[str, str]]:
        """Returns (action, memory id or reason) for each candidate."""
        msgs = [m for m in user_messages if m.strip() and not m.strip().startswith("/")]
        if not msgs:
            return []
        numbered = "\n".join(f"{i + 1}. {m}" for i, m in enumerate(msgs))
        data = self._structured(_prompt("memory_extract.md"), "User messages:\n" + numbered, EXTRACT_SCHEMA)
        if not data:
            return []
        joined = _norm(" \n ".join(msgs))
        results: list[tuple[str, str]] = []
        for cand in data["candidates"]:
            quote = _norm(cand["evidence"])
            if not quote or quote not in joined:
                results.append(("REJECT", "evidence is not a quote of the user"))
                continue
            if find_p3(cand["evidence"] + " " + cand["body"]):
                results.append(("REJECT", "secret data"))
                continue
            mem = Memory(
                name=cand["name"], type=cand["type"], subject=cand["subject"], summary_en=cand["summary_en"],
                keywords=add_script_forms(cand["keywords"], cand["summary_en"]), when_to_use=cand["when_to_use"], sensitivity=cand["sensitivity"],
                evidence=cand["evidence"], source=cand["source"], body=cand["body"],
                confidence="high" if cand["source"] == "user-said" else "medium",
            )
            results.append(self._decide_and_apply(mem, raise_sensitivity(mem)))
        return results

    def _decide_and_apply(self, mem: Memory, auto: list[str] | None = None) -> tuple[str, str]:
        found = self.store.search(f"{mem.name} {mem.summary_en} {mem.keywords}", k=MAX_SIMILAR, time_range=None)
        # Sensitive neighbours stay on this computer: a duplicate of one is caught here without a model,
        # and only P0/P1 neighbours are listed for the model to decide against.
        from jarvis.memory.maintenance import similarity

        for h in found:
            if _private(h.memory) and similarity(_text_of(mem), _text_of(h.memory)) >= PRIVATE_DUPLICATE:
                self.audit.write("memory_skipped", action="NOOP", target=h.memory.id,
                                 reason="duplicate of a private memory (checked locally)")
                return ("NOOP", h.memory.id)
        subject = mem.subject.strip().lower()
        for h in found:  # a newer version of a private memory: same subject, type and name, decided locally
            o = h.memory
            if (_private(o) and subject and o.type == mem.type and o.subject.strip().lower() == subject
                    and similarity(o.name, mem.name) >= PRIVATE_DUPLICATE):
                self.audit.write("memory_decided_locally", action="SUPERSEDE", target=o.id,
                                 reason="newer version of a private memory (same subject, type and name)")
                return self._apply("SUPERSEDE", mem, o.id, auto)
        similar = [h for h in found if not _private(h.memory)]
        if not similar:
            return self._apply("ADD", mem, "", auto)
        listing = "\n".join(
            f"- {h.memory.id} [{h.memory.type}, subject={h.memory.subject}]: {h.memory.summary_en or h.memory.name}"
            for h in similar
        )
        prompt = (f"New candidate [{mem.type}, subject={mem.subject}]: {mem.summary_en}\n"
                  f"Evidence: {mem.evidence}\n\nExisting memories:\n{listing}")
        data = self._structured(_prompt("memory_decide.md"), prompt, DECIDE_SCHEMA)
        if not data:
            return ("REJECT", "no valid decision")
        target = data["target_id"]
        if data["action"] in ("UPDATE", "SUPERSEDE", "NOOP") and target not in {h.memory.id for h in similar}:
            return ("REJECT", f"unknown target {target}")
        return self._apply(data["action"], mem, target, auto)

    def _apply(self, action: str, mem: Memory, target: str, auto: list[str] | None = None) -> tuple[str, str]:
        auto = list(auto or [])
        try:
            if action == "ADD":
                saved = self.store.save(mem)
            elif action == "SUPERSEDE":
                old = self.store.get(target)
                if old is not None:
                    inherit_sensitive(mem, old)  # a newer version of a sensitive memory stays sensitive
                saved = self.store.supersede(target, mem)
            elif action == "UPDATE":
                old = self.store.get(target)
                assert old is not None
                old.body = f"{old.body}\n{mem.body}".strip()
                old.summary_en = mem.summary_en or old.summary_en
                old.keywords = " ".join(dict.fromkeys(f"{old.keywords} {mem.keywords}".split()))
                old.evidence = f"{old.evidence} | {mem.evidence}"
                inherit_sensitive(old, mem)  # merged details keep the candidate's class
                auto = auto or raise_sensitivity(old)
                saved = self.store.update(old)
            else:
                self.audit.write("memory_skipped", action=action, target=target)
                return (action, target or "-")
        except MemoryRejected as e:
            return ("REJECT", str(e))
        self.audit.write("memory_saved", id=saved.id, type=saved.type, how=f"extract:{action}", auto_sensitive=auto)
        return (action, saved.id)
