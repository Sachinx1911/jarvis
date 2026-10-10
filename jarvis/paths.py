"""Where Jarvis keeps code-side files and personal data.

Personal data (memory/, profile/, data/ ...) lives under JARVIS_HOME, which defaults
to the repo root. Those folders are git-ignored; the repo is public.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = REPO_ROOT / "prompts"

PERSONAL_DIRS = (
    "memory/facts",
    "memory/preferences",
    "memory/procedures",
    "memory/episodes",
    "profile",
    "skills",
    "projects",
    "data/tasks",
    "data/sessions",
    "workspace",
    "connectors",
)


@dataclass(frozen=True)
class JarvisPaths:
    home: Path

    @property
    def data(self) -> Path:
        return self.home / "data"

    @property
    def db(self) -> Path:
        return self.data / "jarvis.db"

    @property
    def audit_log(self) -> Path:
        return self.data / "audit.jsonl"

    def ensure(self) -> None:
        for rel in PERSONAL_DIRS:
            (self.home / rel).mkdir(parents=True, exist_ok=True)


def default_paths() -> JarvisPaths:
    home = os.environ.get("JARVIS_HOME")
    return JarvisPaths(Path(home).expanduser().resolve() if home else REPO_ROOT)
