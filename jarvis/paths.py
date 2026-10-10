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


def local_config_path(config_dir: Path | None = None) -> Path:
    """config/local.yaml (machine-specific overrides), or the file named by JARVIS_LOCAL_CONFIG.
    The test suite points that at a file that does not exist, so a developer's own local.yaml
    (wake word on, stored recordings...) never changes what the tests see."""
    override = os.environ.get("JARVIS_LOCAL_CONFIG")
    if override and (config_dir is None or Path(config_dir) == CONFIG_DIR):
        return Path(override)  # only the repository's own local.yaml is replaced; a test's own config dir keeps its file
    return (config_dir or CONFIG_DIR) / "local.yaml"
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
