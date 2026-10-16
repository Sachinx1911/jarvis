"""Workspace files on disk: data/workspaces/<slug>/workspace.yaml and teams/<team>.yaml.

The personal workspace is created the first time it is needed, so every machine has it. Shipped
team templates live in config/teams/*.yaml (public, generic); a workspace copies one with
`add_team(slug, template)` and then owns its copy.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from jarvis.paths import CONFIG_DIR
from jarvis.workspaces.model import (
    PERSONAL,
    Team,
    Workspace,
    WorkspaceError,
    check_slug,
    team_to_dict,
    validate_team,
    validate_workspace,
    workspace_to_dict,
)

WORKSPACE_FILE = "workspace.yaml"
TEAMS_DIR = "teams"


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise WorkspaceError(f"{path.name}: not valid YAML ({e})") from e


def _write_yaml(path: Path, data: dict[str, Any], header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body, encoding="utf-8")


@dataclass
class Problem:
    """A file that could not be loaded; shown instead of crashing."""

    path: str
    error: str


class WorkspaceStore:
    def __init__(self, home: Path, templates_dir: Path | None = None,
                 role_tools: dict[str, frozenset[str]] | None = None):
        self.root = home / "data" / "workspaces"
        self.templates_dir = templates_dir or (CONFIG_DIR / "teams")
        self.role_tools = role_tools
        self.problems: list[Problem] = []

    # ---- workspaces ----

    def path(self, slug: str) -> Path:
        return self.root / check_slug(slug, "workspace slug")

    def ensure_personal(self) -> Workspace:
        p = self.path(PERSONAL) / WORKSPACE_FILE
        if not p.exists():
            w = Workspace(slug=PERSONAL, name="Personal", kind="personal", brief="", language="mr")
            self._save_workspace(w)
        return self.get(PERSONAL)

    def list(self, include_archived: bool = False) -> list[Workspace]:
        self.ensure_personal()
        out: list[Workspace] = []
        self.problems = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or not (d / WORKSPACE_FILE).exists():
                continue
            try:
                w = self._load_workspace(d.name)
            except WorkspaceError as e:
                self.problems.append(Problem(str(d / WORKSPACE_FILE), str(e)))
                continue
            if w.archived and not include_archived:
                continue
            out.append(w)
        out.sort(key=lambda w: (not w.personal, w.name.lower()))
        return out

    def active(self, slug: str) -> Workspace:
        """A workspace a chat or task may work in: it exists and is not archived."""
        w = self.get(slug)
        if w.archived:
            raise WorkspaceError(f"workspace {slug!r} is archived (jarvis workspace unarchive {slug})")
        return w

    def get(self, slug: str) -> Workspace:
        p = self.path(slug) / WORKSPACE_FILE
        if not p.exists():
            if slug == PERSONAL:
                return self.ensure_personal()
            raise WorkspaceError(f"no workspace {slug!r} (see: jarvis workspace list)")
        return self._load_workspace(slug)

    def exists(self, slug: str) -> bool:
        try:
            return (self.path(slug) / WORKSPACE_FILE).exists() or slug == PERSONAL
        except WorkspaceError:
            return False

    def archive(self, slug: str) -> Workspace:
        """End (law 2): the office closes but nothing is deleted. Its memories and tasks keep their tag
        and are seen by nobody until `unarchive`."""
        w = self.get(slug)
        if w.personal:
            raise WorkspaceError("the personal workspace cannot be archived")
        return self.save(replace(w, archived=True))

    def unarchive(self, slug: str) -> Workspace:
        return self.save(replace(self.get(slug), archived=False))

    def _load_workspace(self, slug: str) -> Workspace:
        return validate_workspace(_read_yaml(self.path(slug) / WORKSPACE_FILE), slug)

    def create(self, slug: str, name: str, kind: str = "company", brief: str = "", language: str = "mr") -> Workspace:
        check_slug(slug, "workspace slug")
        if (self.path(slug) / WORKSPACE_FILE).exists():
            raise WorkspaceError(f"workspace {slug!r} already exists")
        w = validate_workspace({"version": 1, "name": name, "kind": kind, "brief": brief, "language": language}, slug)
        self._save_workspace(w)
        return w

    def save(self, w: Workspace) -> Workspace:
        validate_workspace(workspace_to_dict(w), w.slug)  # never write a file we could not read back
        self._save_workspace(w)
        return w

    def _save_workspace(self, w: Workspace) -> None:
        _write_yaml(self.path(w.slug) / WORKSPACE_FILE, workspace_to_dict(w),
                    "# Jarvis workspace (one office). Private: this folder is never committed.\n")

    def workspace_of_project(self, project: str | None) -> str:
        """The workspace a project belongs to; personal when it is listed nowhere."""
        if not project:
            return PERSONAL
        for w in self.list(include_archived=True):
            if project in w.projects:
                return w.slug
        return PERSONAL

    # ---- teams ----

    def teams_dir(self, slug: str) -> Path:
        return self.path(slug) / TEAMS_DIR

    def teams(self, slug: str, include_archived: bool = False) -> list[Team]:
        self.get(slug)
        d = self.teams_dir(slug)
        out: list[Team] = []
        if not d.is_dir():
            return out
        for f in sorted(d.glob("*.yaml")):
            try:
                t = validate_team(_read_yaml(f), f.stem, self.role_tools)
            except WorkspaceError as e:
                self.problems.append(Problem(str(f), str(e)))
                continue
            if t.archived and not include_archived:
                continue
            out.append(t)
        return out

    def team(self, slug: str, team_slug: str) -> Team:
        f = self.teams_dir(slug) / f"{check_slug(team_slug, 'team slug')}.yaml"
        if not f.exists():
            raise WorkspaceError(f"no team {team_slug!r} in workspace {slug!r}")
        return validate_team(_read_yaml(f), team_slug, self.role_tools)

    def templates(self) -> list[Team]:
        out: list[Team] = []
        if self.templates_dir.is_dir():
            for f in sorted(self.templates_dir.glob("*.yaml")):
                try:
                    out.append(validate_team(_read_yaml(f), f.stem, self.role_tools))
                except WorkspaceError as e:
                    self.problems.append(Problem(str(f), str(e)))
        return out

    def add_team(self, slug: str, template: str | None = None, team: Team | None = None) -> Team:
        """Copy a shipped template (or save a given Team) into the workspace; the copy is then its own."""
        self.get(slug)
        if team is None:
            if not template:
                raise WorkspaceError("give a template name (jarvis team templates) or a team")
            src = self.templates_dir / f"{check_slug(template, 'template')}.yaml"
            if not src.exists():
                raise WorkspaceError(f"no team template {template!r} (see: jarvis team templates)")
            team = validate_team(_read_yaml(src), template, self.role_tools)
        dest = self.teams_dir(slug) / f"{team.slug}.yaml"
        if dest.exists():
            raise WorkspaceError(f"team {team.slug!r} already exists in workspace {slug!r}")
        self.save_team(slug, team)
        return team

    def save_team(self, slug: str, team: Team) -> Team:
        validate_team(team_to_dict(team), team.slug, self.role_tools)
        _write_yaml(self.teams_dir(slug) / f"{team.slug}.yaml", team_to_dict(team),
                    "# Jarvis team (part of one workspace). Private: never committed.\n")
        return team

    def archive_team(self, slug: str, team_slug: str) -> Team:
        """End (law 2): the team stops appearing and cannot run; its file and history stay."""
        return self.save_team(slug, replace(self.team(slug, team_slug), archived=True))

    def unarchive_team(self, slug: str, team_slug: str) -> Team:
        return self.save_team(slug, replace(self.team(slug, team_slug), archived=False))
