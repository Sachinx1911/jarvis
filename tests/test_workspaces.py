"""Workspaces step 0 (PLAN.md 18.2, 27): files as truth, validation that names the field, the
personal workspace always there, archive instead of delete, teams from templates that may narrow a
role's tools but never widen them, the rule of sight on memories, and tasks tagged with an owner."""

from __future__ import annotations

import io

import pytest
import yaml

from jarvis.cli import main
from jarvis.db import Store
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryStore
from jarvis.tasks.store import TaskStore
from jarvis.workspaces.model import PERSONAL, Team, WorkspaceError, slugify, validate_team, validate_workspace
from jarvis.workspaces.store import WorkspaceStore


@pytest.fixture
def ws(isolated):
    return WorkspaceStore(isolated)


# ---- model and validation ----

def test_slugify_and_slug_rules():
    assert slugify("Digital Marketing") == "digital-marketing"
    with pytest.raises(WorkspaceError):
        slugify("!")
    with pytest.raises(WorkspaceError, match="workspace slug"):
        validate_workspace({"name": "x"}, "Bad Slug")


def test_validation_names_the_field():
    with pytest.raises(WorkspaceError, match="budget.max_cost"):
        validate_workspace({"name": "x", "budget": {"max_cost": 1}}, "acme")
    with pytest.raises(WorkspaceError, match="language must be one of"):
        validate_workspace({"name": "x", "language": "fr"}, "acme")
    with pytest.raises(WorkspaceError, match="only the 'personal' workspace"):
        validate_workspace({"name": "x", "kind": "personal"}, "acme")
    with pytest.raises(WorkspaceError, match="version 9 is newer"):
        validate_workspace({"name": "x", "version": 9}, "acme")
    with pytest.raises(WorkspaceError, match="cannot be archived"):
        validate_workspace({"name": "Me", "kind": "personal", "archived": True}, PERSONAL)


def test_team_cannot_widen_a_role():
    role_tools = {"researcher": frozenset({"web_search", "web_fetch"})}
    ok = validate_team({"name": "R", "members": [{"role": "researcher", "tools": ["web_search"]}]}, "rs", role_tools)
    assert ok.members[0].tools == ("web_search",)
    with pytest.raises(WorkspaceError, match="may not use delete_file"):
        validate_team({"name": "R", "members": [{"role": "researcher", "tools": ["delete_file"]}]}, "rs", role_tools)
    with pytest.raises(WorkspaceError, match="at least one member"):
        validate_team({"name": "R", "members": []}, "rs")
    with pytest.raises(WorkspaceError, match="used twice"):
        validate_team({"name": "R", "members": [{"role": "writer", "name": "A"}, {"role": "writer", "name": "a"}]}, "rs")


# ---- store: files as truth, personal always present, archive not delete ----

def test_personal_workspace_always_exists(ws, isolated):
    names = [w.slug for w in ws.list()]
    assert names == [PERSONAL]
    assert (isolated / "data" / "workspaces" / PERSONAL / "workspace.yaml").exists()
    assert ws.get(PERSONAL).personal


def test_create_show_edit_archive_unarchive(ws, isolated):
    from dataclasses import replace

    w = ws.create("acme", "Acme Ltd", brief="demo")
    path = isolated / "data" / "workspaces" / "acme" / "workspace.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for limb in ("name", "duties", "projects", "tools", "budget", "allies"):  # saptanga: every limb present
        assert limb in data, limb
    ws.save(replace(w, duties=("ads",), share_personal=False))
    again = ws.get("acme")
    assert again.duties == ("ads",) and again.share_personal is False
    with pytest.raises(WorkspaceError, match="already exists"):
        ws.create("acme", "Again")
    ws.archive("acme")
    assert [w.slug for w in ws.list()] == [PERSONAL]
    assert [w.slug for w in ws.list(include_archived=True)] == [PERSONAL, "acme"]
    assert path.exists()  # law 2: nothing deleted
    with pytest.raises(WorkspaceError, match="archived"):
        ws.active("acme")
    ws.unarchive("acme")
    assert ws.active("acme").slug == "acme"
    with pytest.raises(WorkspaceError, match="cannot be archived"):
        ws.archive(PERSONAL)


def test_broken_file_is_reported_not_loaded(ws, isolated):
    ws.create("acme", "Acme")
    bad = isolated / "data" / "workspaces" / "broken"
    bad.mkdir(parents=True)
    (bad / "workspace.yaml").write_text("name: [oops\n", encoding="utf-8")
    assert [w.slug for w in ws.list()] == [PERSONAL, "acme"]
    assert ws.problems and "broken" in ws.problems[0].path


def test_teams_from_templates_are_owned_copies(ws, isolated):
    ws.create("acme", "Acme")
    names = [t.slug for t in ws.templates()]
    assert {"research", "content", "dev", "admin"} <= set(names)
    t = ws.add_team("acme", template="research")
    f = isolated / "data" / "workspaces" / "acme" / "teams" / "research.yaml"
    assert f.exists() and t.members
    with pytest.raises(WorkspaceError, match="already exists"):
        ws.add_team("acme", template="research")
    with pytest.raises(WorkspaceError, match="no team template"):
        ws.add_team("acme", template="nope")
    ws.archive_team("acme", "research")
    assert ws.teams("acme") == [] and [x.slug for x in ws.teams("acme", include_archived=True)] == ["research"]
    assert f.exists()
    ws.unarchive_team("acme", "research")
    assert [x.slug for x in ws.teams("acme")] == ["research"]
    custom = Team(slug="ops", name="Ops", members=(validate_team({"name": "O", "members": [{"role": "writer"}]}, "ops").members))
    ws.add_team("acme", team=custom)
    assert ws.team("acme", "ops").name == "Ops"


def test_project_owner(ws):
    from dataclasses import replace

    w = ws.create("acme", "Acme")
    ws.save(replace(w, projects=("launch",)))
    assert ws.workspace_of_project("launch") == "acme"
    assert ws.workspace_of_project("other") == PERSONAL
    assert ws.workspace_of_project(None) == PERSONAL


# ---- the rule of sight (law 4) ----

def test_memory_visibility(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        mem = MemoryStore(isolated, store)
        mine = mem.save(Memory(name="my tea", body="I drink tea", evidence="I drink tea", keywords="tea chai"))
        acme = mem.save(Memory(name="acme tea", body="acme office tea budget", evidence="acme tea", keywords="tea budget",
                               workspace="acme"))
        other = mem.save(Memory(name="globex tea", body="globex tea vendor", evidence="globex tea", keywords="tea vendor",
                                workspace="globex"))
        shared = mem.save(Memory(name="tea rule", body="tea at 4", evidence="tea at 4", keywords="tea", workspace="shared"))
        ids = lambda **kw: {h.memory.id for h in mem.search("tea", k=10, **kw)}
        assert ids() == {mine.id, acme.id, other.id, shared.id}                      # no filter
        assert ids(workspace="acme") == {mine.id, acme.id, shared.id}                # own + personal + shared
        assert ids(workspace="acme", share_personal=False) == {acme.id, shared.id}   # personal out of view
        assert ids(workspace=PERSONAL) == {mine.id, shared.id}                        # never another company's
        assert other.id not in ids(workspace="acme")
        assert MemoryStore.visible(other, "acme") is False
    finally:
        store.close()


def test_task_carries_its_owner(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        ts = TaskStore(store, isolated / "data" / "tasks")
        t = ts.create("do it", workspace="acme")
        assert ts.get(t.id).workspace == "acme"
        assert ts.create("plain").workspace == PERSONAL
        assert store.conn.execute("SELECT workspace FROM tasks WHERE id=?", (t.id,)).fetchone() == ("acme",)
    finally:
        store.close()


# ---- CLI ----

def test_cli_workspace_and_team_flow(isolated):
    out = io.StringIO()
    assert main(["workspace", "new", "acme", "--name", "Acme Ltd"], out=out) == 0
    assert main(["team", "add", "acme", "--from", "dev"], out=out) == 0
    assert main(["workspace", "edit", "acme", "--duty", "ship code", "--share-personal", "no"], out=out) == 0
    assert main(["workspace", "show", "acme"], out=out) == 0
    assert main(["team", "list", "acme"], out=out) == 0
    assert main(["workspace", "archive", "acme"], out=out) == 0
    assert main(["workspace", "archive", "personal"], out=out) == 1
    assert main(["team", "add", "nope", "--from", "dev"], out=out) == 1
    text = out.getvalue()
    assert "Acme Ltd" in text and "ship code" in text and "personal memories in view: no" in text
    assert "dev " in text and "Archived acme" in text and "cannot be archived" in text and "no workspace" in text


def test_chat_workspace_command_scopes_memory(isolated):
    """/workspace in chat: /remember goes to that office and a company never sees another's memory."""
    out = io.StringIO()
    main(["workspace", "new", "acme", "--name", "Acme"], out=io.StringIO())
    main(["workspace", "new", "globex", "--name", "Globex"], out=io.StringIO())
    inp = io.StringIO("/workspace acme\n/remember acme vendor is demo-corp\n/workspace globex\n/memory vendor\n/workspace off\n/memory vendor\n/exit\n")
    assert main(["chat", "--provider", "fake"], out=out, inp=inp) == 0
    text = out.getvalue()
    assert "Workspace: Acme (acme)" in text and "Remembered as m-0001" in text
    store = Store(isolated / "data" / "jarvis.db")
    try:
        assert store.conn.execute("SELECT workspace FROM memory_index WHERE id='m-0001'").fetchone() == ("acme",)
    finally:
        store.close()
