"""The kinds registry (PLAN.md 27.1 law 1, 27.2, 27.7).

Every kind of thing Jarvis knows or does declares itself here: which store holds it, which methods
are its three powers (create, preserve, end: the Trimurti in every part), which field names its
owner (the workspace, law 4), where its truth lives (a human-readable file or a table), and which
marks of law 1 it carries. `tests/test_laws.py` reads this registry and fails for any kind that
does not have all three powers, so a new kind cannot be added without them.

A kind that still lacks something says so in `gaps` with the step that closes it (27.6). The test
treats a declared gap as known and an undeclared one as a failure: honesty, not perfection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Marks of law 1. A kind names where each mark lives; "-" means it does not apply and says why in `notes`.
MARKS = ("id", "kind", "owner", "source", "when", "confidence", "privacy")


@dataclass(frozen=True)
class Kind:
    name: str                       # the kind, as used in audit events and the Office page
    store: str                      # "module:Class" of the store that owns it
    create: str                     # Brahma: the method that brings one into being, validated
    preserve: tuple[str, ...]       # Vishnu: read/update methods that keep it (get, list, save/update...)
    end: str | None                 # Mahesh: archive / supersede / cancel; None = a declared gap
    truth: str                      # "file" (human-readable file is the truth, SQLite indexes it) or "table"
    owner_field: str | None         # the workspace field (law 4); None only with a reason in `notes`
    marks: dict[str, str] = field(default_factory=dict)   # mark -> field name holding it
    rites: tuple[str, ...] = ()     # sanskaras: audit event names it emits (27.10)
    gaps: tuple[str, ...] = ()      # known shortfalls and the step that closes each
    notes: str = ""


KINDS: tuple[Kind, ...] = (
    Kind("workspace", "jarvis.workspaces.store:WorkspaceStore", "create", ("get", "list", "save"), "archive",
         "file", None, {"id": "slug", "kind": "kind", "source": "-", "when": "-", "confidence": "-", "privacy": "-"},
         ("workspace_created", "workspace_edited", "workspace_archived", "workspace_unarchived"),
         notes="A workspace is itself the owner (law 4); it has no owner field. Files: data/workspaces/<slug>/workspace.yaml."),
    Kind("team", "jarvis.workspaces.store:WorkspaceStore", "add_team", ("team", "teams", "save_team"), "archive_team",
         "file", "workspace", {"id": "slug", "kind": "-", "source": "-", "when": "-", "confidence": "-", "privacy": "-"},
         ("team_added", "team_archived", "team_unarchived"),
         notes="Lives inside its workspace folder (teams/<slug>.yaml); the folder is the owner."),
    Kind("memory", "jarvis.memory.store:MemoryStore", "save", ("get", "list", "update", "search"), "archive",
         "file", "workspace",
         {"id": "id", "kind": "type", "owner": "workspace", "source": "source", "when": "valid_from",
          "confidence": "confidence", "privacy": "sensitivity"},
         ("memory_saved", "memory_skipped", "memory_archived"),
         notes="Also supersede (end-by-replacement) and trash/restore (Sachin's explicit, logged act)."),
    Kind("task", "jarvis.tasks.store:TaskStore", "create", ("get", "list", "update"), "set_state",
         "table", "workspace",
         {"id": "id", "kind": "-", "owner": "workspace", "source": "owner", "when": "created_at",
          "confidence": "-", "privacy": "-"},
         ("created", "state", "receipt"),
         gaps=("file truth: tasks live only in SQLite; a task folder with receipt.md exists but is not the truth (27.8 item 10, step 1-2)",
               "end is set_state(CANCELLED), not archive: step 1 adds archive for finished tasks"),
         notes="`source` is the owner column: jarvis, an agent name, or a schedule."),
    Kind("schedule", "jarvis.proactive.scheduler:ScheduleStore", "add", ("get", "list"), "archive",
         "table", "workspace",
         {"id": "id", "kind": "kind", "owner": "workspace", "source": "source", "when": "created_at",
          "confidence": "-", "privacy": "-"},
         gaps=("file truth: step 1-2 (27.8 item 10)",),
         notes="archive/unarchive keep the row; delete_forever removes an archived row only, as Sachin's logged act."),
    Kind("trigger", "jarvis.proactive.triggers:TriggerStore", "add", ("get", "list"), "archive",
         "table", "workspace",
         {"id": "id", "kind": "source", "owner": "workspace", "source": "created_by", "when": "created_at",
          "confidence": "-", "privacy": "-"},
         notes="archive/unarchive keep the row and what it has seen; delete_forever is Sachin's logged act."),
    Kind("reminder", "jarvis.proactive.reminders:ReminderStore", "add", ("get", "pending", "upcoming"), "cancel",
         "table", "workspace",
         {"id": "id", "kind": "-", "owner": "workspace", "source": "source", "when": "created_at",
          "confidence": "-", "privacy": "-"},
         notes="cancel keeps the row with status cancelled (an end, not a delete)."),
    Kind("skill", "jarvis.skills.loader:SkillLibrary", "-", ("index", "load"), None,
         "file", None,
         {"id": "name", "kind": "-", "source": "-", "when": "-", "confidence": "-", "privacy": "-"},
         gaps=("create lives in the recorder (approve), not in the library: step 1 moves it or declares it here",
               "no archive for skills: step 1",
               "no owner field: step 1 (a skill belongs to a workspace or is shared)")),
    Kind("project", "jarvis.projects:ProjectStore", "create", ("list", "context"), None,
         "file", None,
         {"id": "name", "kind": "-", "source": "-", "when": "-", "confidence": "-", "privacy": "-"},
         gaps=("no archive for projects: step 1",
               "owner is the workspace's `projects` list, not a field on the project: step 1 decides which side holds it")),
    Kind("document", "jarvis.docs.library:DocLibrary", "index", ("documents", "search"), None,
         "file", None,
         {"id": "file", "kind": "-", "source": "project", "when": "doc_date", "confidence": "-", "privacy": "privacy"},
         gaps=("end: a document is removed by deleting the file; step 1 adds archive (moves it out of docs/)",
               "owner follows the project, not a field of its own: step 1 (27.6 item 1)")),
    Kind("grant", "jarvis.control.grants:GrantStore", "create", ("get", "list"), "revoke",
         "table", None,
         {"id": "id", "kind": "tool", "source": "created_by", "when": "created_at", "confidence": "-", "privacy": "-"},
         notes="A standing approval binds the whole machine, not one workspace, by design (law 5: one gate)."),
    Kind("approval", "jarvis.proactive.scheduler:PendingApprovals", "add", ("get", "list"), "set_status",
         "table", None,
         {"id": "id", "kind": "tool", "source": "schedule_id", "when": "created_at", "confidence": "-", "privacy": "-"},
         notes="Decided (approved/denied/dismissed) is its end; rows are kept."),
    Kind("audit", "jarvis.control.audit:AuditLog", "write", (), "-",
         "file", None,
         {"id": "-", "kind": "event", "source": "-", "when": "ts", "confidence": "-", "privacy": "-"},
         notes="Chitragupta's register: append-only by law 3; it belongs to no loka and is never ended."),
)


def by_name(name: str) -> Kind:
    for k in KINDS:
        if k.name == name:
            return k
    raise KeyError(name)


def declared_gaps() -> dict[str, tuple[str, ...]]:
    return {k.name: k.gaps for k in KINDS if k.gaps}
