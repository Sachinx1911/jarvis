"""The session rule (PLAN.md 18.2 step 0, law 4): a chat has one workspace.

`/workspace <slug>` enters it; `/project <name>` enters the project's owner. Entering a workspace drops
an active project that belongs elsewhere. Both the terminal chat and the dashboard chat call this, so
the rule lives here and nowhere else.
"""

from __future__ import annotations

from jarvis.workspaces.model import Workspace
from jarvis.workspaces.store import WorkspaceStore


def enter_workspace(session, store: WorkspaceStore, slug: str) -> Workspace:
    """Make `slug` the session's workspace; raises WorkspaceError if it is unknown or archived."""
    w = store.active(slug)
    session.set_workspace(w.slug, w.share_personal)
    project = getattr(session.context, "project", None)
    if project and store.workspace_of_project(project) != w.slug:
        session.context.project = None  # a project of another office does not follow into this one
    return w
