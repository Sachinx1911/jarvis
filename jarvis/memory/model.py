"""One memory = one markdown file with YAML frontmatter (PLAN.md 6.2)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any

import yaml

TYPES = ("fact", "preference", "procedure", "constraint", "episode")
TYPE_DIRS = {
    "fact": "facts",
    "preference": "preferences",
    "procedure": "procedures",
    "constraint": "constraints",
    "episode": "episodes",
}
STATUSES = ("active", "superseded", "archived")
SOURCES = ("user-said", "inferred", "imported")
SENSITIVITIES = ("public", "normal", "sensitive", "secret")


@dataclass
class Memory:
    name: str
    type: str = "fact"
    body: str = ""
    id: str = ""
    status: str = "active"
    subject: str = ""
    description: str = ""
    when_to_use: str = ""
    summary_en: str = ""
    keywords: str = ""
    evidence: str = ""
    source: str = "user-said"
    confidence: str = "high"
    sensitivity: str = "normal"
    scope: str = ""
    valid_from: str = field(default_factory=lambda: date.today().isoformat())
    valid_until: str = ""
    superseded_by: str = ""
    last_used: str = ""
    use_count: int = 0
    expires: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("memory needs a name")
        if self.type not in TYPES:
            raise ValueError(f"type must be one of {TYPES}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity must be one of {SENSITIVITIES}")
        if not self.evidence.strip():
            raise ValueError("memory needs evidence: a quote of the user's own words")

    def search_text(self) -> str:
        return " ".join([self.name, self.subject, self.description, self.when_to_use,
                         self.summary_en, self.keywords, self.evidence, self.body])

    def to_markdown(self) -> str:
        meta = {k: v for k, v in asdict(self).items() if k != "body"}
        front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000)
        return f"---\n{front}---\n{self.body.strip()}\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Memory":
        m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.DOTALL)
        if not m:
            raise ValueError("missing frontmatter")
        meta: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
        known = {f.name for f in fields(cls)}
        data = {k: ("" if v is None else v) for k, v in meta.items() if k in known}
        if "use_count" in data:
            data["use_count"] = int(data["use_count"] or 0)
        for k in ("valid_from", "valid_until", "last_used", "expires"):
            if k in data and not isinstance(data[k], str):
                data[k] = str(data[k])
        return cls(body=m.group(2).strip(), **data)


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return (slug[:limit].rstrip("-")) or "memory"
