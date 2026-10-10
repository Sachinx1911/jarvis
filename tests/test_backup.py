"""Local backups: create, prune, list, restore-check. Synthetic data only (the repo is public)."""

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import sys
import tarfile
from datetime import datetime, timedelta

import pytest

from jarvis import backup, cli_backup
from jarvis.backup import MAIN_DB, MANIFEST_NAME, BackupError, BackupSettings
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.paths import REPO_ROOT

T0 = datetime(2026, 10, 10, 9, 30, 0)

INCLUDED = {
    "memory/facts/m-001-favourite-tea.md": "Likes masala chai (made-up example).",
    "memory/MEMORY.md": "# Memory index\n",
    "memory/.trash/m-000-old-note.md": "a deleted memory stays restorable",
    "profile/SOUL.md": "Be brief.",
    "skills/weekly-plan/SKILL.md": "# Weekly plan",
    "projects/demo/PROJECT.md": "# demo",
    "projects/loose/readme.txt": "not a project (no PROJECT.md)",
    "workspace/notes.txt": "hello",
    "workspace/मराठी-टीप.txt": "a Devanagari file name",
    "workspace/app/yarn.lock": "a project lock file is data, not a runtime lock",
    "connectors/registry.yaml": "connectors: {}\n",
    "data/tasks/t-1/plan.json": "{}",
    "data/audit.jsonl": '{"event": "example"}\n',
}
EXCLUDED = {
    "data/browser/default/Cookies": "session=fake",
    "workspace/.env": "API_KEY=fake",
    "workspace/app/.env.local": "X=1",
    "workspace/server.key": "fake key",
    "workspace/certs/site.pem": "fake cert",
    "connectors/client_secret_123.apps.googleusercontent.com.json": "{}",
    "workspace/.trash/20261001-old.txt": "trashed",
    "workspace/app/__pycache__/m.cpython-313.pyc": "cache",
    "workspace/app/node_modules/pkg/index.js": "cache",
    "data/models/whisper/model.bin": "downloaded model",
    "data/app.lock": "",
}


@pytest.fixture(autouse=True)
def fake_user_home(tmp_path, monkeypatch):
    """~ points into tmp_path, so no test can reach the real ~/JarvisBackups."""
    user = tmp_path / "userhome"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    return user


@pytest.fixture
def home(tmp_path):
    """JARVIS_HOME (tmp_path, from conftest) filled with made-up personal data and a database."""
    for rel, text in {**INCLUDED, **EXCLUDED}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    store = Store(tmp_path / "data" / "jarvis.db")
    store.conn.executemany("INSERT INTO tasks (id, title, state) VALUES (?, ?, ?)",
                           [("t-1", "Plan a trip (example)", "done"), ("t-2", "Compare laptops", "queued")])
    store.conn.commit()
    store.close()
    return tmp_path


@pytest.fixture
def cfg(tmp_path):
    """A config folder with a machine-specific local.yaml (it is backed up as config/local.yaml)."""
    d = tmp_path / "cfg"
    d.mkdir()
    (d / "local.yaml").write_text("proactive_file:\n  brief:\n    place: Exampletown\n", encoding="utf-8")
    return d


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "out" / "JarvisBackups"


@pytest.fixture
def audit(home):
    return AuditLog(home / "data" / "audit.jsonl")


def _settings(dest, keep_last=14, exclude=()):
    return BackupSettings(str(dest), keep_last, tuple(exclude))


def _create(home, dest, cfg, audit=None, now=T0, **kw):
    return backup.create_backup(home, _settings(dest, **kw), audit, config_dir=cfg, now=now)


def _members(archive):
    with tarfile.open(archive, "r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isreg()}, \
            [m.name for m in tar.getmembers()]


def _events(home, name):
    path = home / "data" / "audit.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [e for e in lines if e.get("event") == name]


# ---- create ----

def test_create_archives_personal_data_with_a_manifest(home, cfg, dest, audit):
    result = _create(home, dest, cfg, audit)
    assert result.path.name == "jarvis-backup-20261010-093000.tar.gz"
    data, order = _members(result.path)
    for rel, text in INCLUDED.items():
        assert data[rel] == text.encode("utf-8"), rel
    assert data["config/local.yaml"].startswith(b"proactive_file:")
    assert MAIN_DB in data
    assert order[-1] == MANIFEST_NAME

    manifest = json.loads(data[MANIFEST_NAME])
    assert manifest["format_version"] == backup.FORMAT_VERSION
    assert manifest["created_at"] == "2026-10-10T09:30:00"
    assert manifest["sqlite_snapshots"] == [MAIN_DB]
    listed = {e["path"]: e for e in manifest["files"]}
    assert set(listed) == set(data) - {MANIFEST_NAME}
    for rel, entry in listed.items():
        assert entry["size"] == len(data[rel])
        assert entry["sha256"] == hashlib.sha256(data[rel]).hexdigest()
    assert result.files == len(listed)
    assert manifest["code_commit"] is None or len(manifest["code_commit"]) >= 40


def test_create_takes_the_database_through_the_backup_api_as_a_consistent_snapshot(home, cfg, dest, tmp_path):
    live = sqlite3.connect(home / "data" / "jarvis.db")
    live.execute("BEGIN IMMEDIATE")
    live.execute("INSERT INTO tasks (id, title, state) VALUES ('t-3', 'not committed yet', 'queued')")
    try:
        result = _create(home, dest, cfg)
    finally:
        live.rollback()
        live.close()
    data, _ = _members(result.path)
    assert not [n for n in data if n.endswith(("-journal", "-wal", "-shm"))]
    copy = tmp_path / "copy.db"
    copy.write_bytes(data[MAIN_DB])
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert [r[0] for r in conn.execute("SELECT id FROM tasks ORDER BY id")] == ["t-1", "t-2"]
    finally:
        conn.close()


def test_create_leaves_out_cookies_secrets_trash_caches_and_symlinks(home, cfg, dest, tmp_path):
    outside = tmp_path / "elsewhere" / "private.txt"
    outside.parent.mkdir()
    outside.write_text("outside JARVIS_HOME", encoding="utf-8")
    try:
        os.symlink(outside, home / "workspace" / "link.txt")
        os.symlink(outside.parent, home / "workspace" / "linked-dir")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    result = _create(home, dest, cfg)
    data, _ = _members(result.path)
    for rel in EXCLUDED:
        assert rel not in data, rel
    assert not [n for n in data if "link" in n.split("/")[-1] or n.startswith("workspace/linked-dir")]
    assert not any(b"outside JARVIS_HOME" == v for v in data.values())
    assert result.excluded["browser profiles (login cookies)"] == 1
    assert result.excluded["secret files (.env, keys, certificates)"] == 5
    assert result.excluded["symlinks"] == 2


def test_config_excludes_add_patterns(home, cfg, dest):
    result = _create(home, dest, cfg, exclude=["workspace/app", "*.txt"])
    data, _ = _members(result.path)
    assert "workspace/app/yarn.lock" not in data
    assert "workspace/notes.txt" not in data and "projects/loose/readme.txt" not in data
    assert "profile/SOUL.md" in data


def test_backup_folder_under_jarvis_home_is_never_archived(home, cfg):
    inside = home / "workspace" / "backups"
    _create(home, inside, cfg, now=T0)
    second = _create(home, inside, cfg, now=T0 + timedelta(seconds=1))
    data, _ = _members(second.path)
    assert not [n for n in data if n.startswith("workspace/backups")]
    assert "workspace/notes.txt" in data


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_folder_is_owner_only_and_archives_are_0600(home, cfg, dest):
    result = _create(home, dest, cfg)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert not list(dest.glob(".*.partial"))


def test_audit_log_has_counts_but_no_contents(home, cfg, dest, audit):
    _create(home, dest, cfg, audit)
    [event] = _events(home, "backup_create")
    assert event["ok"] is True and event["archive"] == "jarvis-backup-20261010-093000.tar.gz"
    assert event["files"] > 0 and event["sqlite_snapshots"] == 1
    text = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "masala" not in text and "favourite-tea" not in text and "Exampletown" not in text


# ---- keep_last ----

def test_keep_last_prunes_only_older_jarvis_archives(home, cfg, dest, audit):
    dest.mkdir(parents=True)
    others = ["notes.txt", "jarvis-backup-notes.txt", "other-backup.tar.gz", "jarvis-backup-2026.tar.gz"]
    for name in others:
        (dest / name).write_text("not a Jarvis archive", encoding="utf-8")
    made = [_create(home, dest, cfg, audit, now=T0 + timedelta(days=i), keep_last=2).path.name for i in range(4)]
    kept = sorted(p.name for p in backup.archives_in(dest))
    assert kept == made[-2:]
    for name in others:
        assert (dest / name).exists(), name
    removed = [name for e in _events(home, "backup_prune") for name in e["removed"]]
    assert removed == made[:2]


def test_same_second_gets_a_numbered_name_and_prunes_in_order(home, cfg, dest):
    names = [_create(home, dest, cfg, now=T0, keep_last=2).path.name for _ in range(3)]
    assert names == ["jarvis-backup-20261010-093000.tar.gz", "jarvis-backup-20261010-093000-2.tar.gz",
                     "jarvis-backup-20261010-093000-3.tar.gz"]
    assert [p.name for p in backup.archives_in(dest)] == names[1:]


# ---- destination rules ----

@pytest.mark.parametrize("raw", [
    str(REPO_ROOT),
    str(REPO_ROOT / "backups-never-created"),
    str(REPO_ROOT / "data" / "backups-never-created"),
    str(REPO_ROOT / "config" / ".." / "backups-never-created"),
])
def test_destination_inside_the_repo_is_refused(home, cfg, audit, raw):
    with pytest.raises(BackupError, match="inside the code repository"):
        backup.create_backup(home, BackupSettings(raw, 14), audit, config_dir=cfg, now=T0)
    assert not (REPO_ROOT / "backups-never-created").exists()
    assert not (REPO_ROOT / "data" / "backups-never-created").exists()
    [event] = _events(home, "backup_create")
    assert event["ok"] is False


def test_repo_reached_through_a_symlink_is_refused(tmp_path):
    alias = tmp_path / "repo-alias"
    try:
        os.symlink(REPO_ROOT, alias, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    with pytest.raises(BackupError, match="inside the code repository"):
        backup.check_destination(alias / "backups")


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="case-insensitive file systems")
def test_repo_path_in_other_letter_case_is_refused():
    with pytest.raises(BackupError, match="inside the code repository"):
        backup.check_destination(str(REPO_ROOT).swapcase() + os.sep + "backups")


def test_relative_destination_is_refused():
    with pytest.raises(BackupError, match="absolute"):
        backup.check_destination("backups")


def test_default_destination_is_under_the_user_home(fake_user_home):
    assert backup.check_destination("~/JarvisBackups") == (fake_user_home / "JarvisBackups").resolve()


# ---- settings ----

def test_settings_from_shipped_file_and_local_override(tmp_path):
    d = tmp_path / "cfg2"
    d.mkdir()
    shutil.copyfile(REPO_ROOT / "config" / "backup.yaml", d / "backup.yaml")
    assert backup.load_backup_settings(d) == BackupSettings("~/JarvisBackups", 14, ())
    (d / "local.yaml").write_text("backup_file:\n  destination: /tmp/elsewhere\n  keep_last: 3\n"
                                  "  exclude: [workspace/videos]\n", encoding="utf-8")
    assert backup.load_backup_settings(d) == BackupSettings("/tmp/elsewhere", 3, ("workspace/videos",))


@pytest.mark.parametrize("raw", [{"keep_last": 0}, {"keep_last": "7"}, {"keep_last": True},
                                 {"destination": ""}, {"exclude": [1]}])
def test_invalid_settings_are_refused(raw):
    with pytest.raises(BackupError):
        backup.settings_from_dict({**backup.DEFAULTS, **raw})


# ---- list ----

def test_list_shows_archives_newest_first_and_flags_unreadable_ones(home, cfg, dest):
    first = _create(home, dest, cfg, now=T0)
    second = _create(home, dest, cfg, now=T0 + timedelta(hours=1))
    (dest / "jarvis-backup-20200101-000000.tar.gz").write_bytes(b"not a gzip file")
    items = backup.list_backups(dest)
    assert [i.path.name for i in items] == [second.path.name, first.path.name,
                                             "jarvis-backup-20200101-000000.tar.gz"]
    assert items[0].manifest_ok and items[0].files == second.files
    assert items[0].created == "2026-10-10 10:30:00" and items[0].size == second.path.stat().st_size
    assert not items[2].manifest_ok and items[2].files is None


def test_list_of_a_missing_folder_is_empty(tmp_path):
    assert backup.list_backups(tmp_path / "nothing-here") == []


# ---- restore-check ----

def _live_state(home):
    """Hash and mtime of every live file except the audit log (which gets one new line)."""
    out = {}
    for path in sorted(home.rglob("*")):
        rel = path.relative_to(home).as_posix()
        if path.is_file() and not path.is_symlink() and rel != "data/audit.jsonl" and not rel.startswith("out/"):
            out[rel] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    return out


def test_restore_check_passes_and_reports_counts(home, cfg, dest, audit, tmp_path):
    result = _create(home, dest, cfg)
    checks = tmp_path / "checks"
    checks.mkdir()
    report = backup.restore_check(result.path, audit, tmp_root=checks)
    assert report.ok, report.problems
    assert report.files_checked == result.files
    assert report.databases == {MAIN_DB: "ok"}
    assert (report.memory_files, report.projects, report.tasks) == (1, 1, 2)
    assert report.created_at == "2026-10-10T09:30:00"
    assert list(checks.iterdir()) == []  # the temporary copy is gone
    [event] = _events(home, "backup_restore_check")
    assert event["ok"] is True and event["tasks"] == 2


def test_restore_check_never_touches_live_data(home, cfg, dest, audit):
    result = _create(home, dest, cfg, audit)
    (home / "memory" / "facts" / "m-001-favourite-tea.md").unlink()  # live data changes after the backup
    before = _live_state(home)
    audit_before = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    report = backup.restore_check(result.path, audit)
    assert report.ok and report.memory_files == 1  # counted from the archive, not from live data
    assert _live_state(home) == before
    assert not (home / "memory" / "facts" / "m-001-favourite-tea.md").exists()
    audit_after = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert audit_after.startswith(audit_before)
    assert [json.loads(line)["event"] for line in audit_after[len(audit_before):].splitlines()] == [
        "backup_restore_check"]


def _rewrite(src, out, change=None, drop=(), add=None):
    """Copy an archive, changing, dropping or adding members (the manifest is copied as is)."""
    with tarfile.open(src, "r:gz") as tin, tarfile.open(out, "w:gz") as tout:
        for m in tin.getmembers():
            if m.name in drop:
                continue
            data = (change or {}).get(m.name, tin.extractfile(m).read())
            m.size = len(data)
            tout.addfile(m, io.BytesIO(data))
        for name, data in (add or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tout.addfile(info, io.BytesIO(data))


def test_checksum_mismatch_is_reported(home, cfg, dest, tmp_path):
    result = _create(home, dest, cfg)
    bad = tmp_path / "tampered.tar.gz"
    _rewrite(result.path, bad, change={"profile/SOUL.md": b"Be BRIEF."})  # same size, other bytes
    report = backup.restore_check(bad)
    assert not report.ok
    assert report.problems == ["profile/SOUL.md: checksum does not match the manifest"]


def test_missing_and_unlisted_members_are_reported(home, cfg, dest, tmp_path):
    result = _create(home, dest, cfg)
    bad = tmp_path / "changed.tar.gz"
    _rewrite(result.path, bad, drop={"workspace/notes.txt"}, add={"workspace/extra.txt": b"added later"})
    problems = backup.restore_check(bad).problems
    assert "workspace/extra.txt: in the archive but not in the manifest" in problems
    assert "workspace/notes.txt: listed in the manifest but missing from the archive" in problems


def test_damaged_database_fails_the_integrity_check(home, cfg, dest, tmp_path):
    result = _create(home, dest, cfg)
    data, _ = _members(result.path)
    db = bytearray(data[MAIN_DB])
    db[100:4096] = b"\xff" * (4096 - 100)  # wreck the schema page
    manifest = json.loads(data[MANIFEST_NAME])
    for entry in manifest["files"]:
        if entry["path"] == MAIN_DB:
            entry["sha256"] = hashlib.sha256(bytes(db)).hexdigest()
    bad = tmp_path / "bad-db.tar.gz"
    _rewrite(result.path, bad, change={MAIN_DB: bytes(db), MANIFEST_NAME: json.dumps(manifest).encode()})
    report = backup.restore_check(bad)
    assert not report.ok
    assert report.databases[MAIN_DB] != "ok"
    assert any(p.startswith(MAIN_DB) for p in report.problems)


def _evil_archive(path, member: tarfile.TarInfo, data: bytes = b"escaped"):
    good = b"fine"
    manifest = {"format_version": 1, "created_at": "2026-10-10T09:30:00", "sqlite_snapshots": [],
                "files": [{"path": "profile/SOUL.md", "size": len(good), "sha256": hashlib.sha256(good).hexdigest()},
                          {"path": member.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
    body = json.dumps(manifest).encode()
    with tarfile.open(path, "w:gz") as tar:
        ok = tarfile.TarInfo("profile/SOUL.md")
        ok.size = len(good)
        tar.addfile(ok, io.BytesIO(good))
        if member.isreg():
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
        else:
            tar.addfile(member)
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))


def _link(name, kind, target):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, target
    return info


@pytest.mark.parametrize("member", [
    tarfile.TarInfo("../escape.txt"),
    tarfile.TarInfo("data/../../escape.txt"),
    tarfile.TarInfo("/tmp/jarvis-escape.txt"),
    tarfile.TarInfo("C:/escape.txt"),
    _link("workspace/link", tarfile.SYMTYPE, "../../escape.txt"),
    _link("workspace/hard", tarfile.LNKTYPE, "/etc/hosts"),
], ids=["dotdot", "nested-dotdot", "absolute", "drive", "symlink", "hardlink"])
def test_unsafe_members_are_rejected_before_anything_is_extracted(tmp_path, member):
    archive = tmp_path / "out" / "evil.tar.gz"
    archive.parent.mkdir()
    _evil_archive(archive, member)
    checks = tmp_path / "checks"
    checks.mkdir()
    report = backup.restore_check(archive, tmp_root=checks)
    assert not report.ok
    assert "unsafe archive members, nothing was extracted" in report.problems[0]
    assert report.files_checked == 0
    assert list(checks.iterdir()) == []
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path.parent / "escape.txt").exists()


def test_unreadable_archive_is_reported(tmp_path):
    junk = tmp_path / "jarvis-backup-20261010-093000.tar.gz"
    junk.write_bytes(b"\x1f\x8b not really gzip")
    report = backup.restore_check(junk)
    assert not report.ok and "cannot be read" in report.problems[0]


def test_find_archive_latest_name_and_path(home, cfg, dest):
    first = _create(home, dest, cfg, now=T0).path
    second = _create(home, dest, cfg, now=T0 + timedelta(minutes=5)).path
    assert backup.find_archive("latest", dest) == second
    assert backup.find_archive(first.name, dest) == first
    assert backup.find_archive(str(first), None) == first
    with pytest.raises(BackupError):
        backup.find_archive("jarvis-backup-19990101-000000.tar.gz", dest)
    with pytest.raises(BackupError, match="no backups"):
        backup.find_archive("latest", dest / "empty")


# ---- CLI ----

@pytest.fixture
def cli(monkeypatch, cfg, dest, home):
    (cfg / "local.yaml").write_text(f"backup_file:\n  destination: {json.dumps(str(dest))}\n  keep_last: 5\n",
                                    encoding="utf-8")
    monkeypatch.setattr(cli_backup, "CONFIG_DIR", cfg)
    parser = argparse.ArgumentParser()
    handlers = cli_backup.register(parser.add_subparsers(dest="command"))
    assert set(handlers) == {"backup"}

    def run(*argv):
        out = io.StringIO()
        code = handlers["backup"](parser.parse_args(["backup", *argv]), out, io.StringIO(), None)
        return code, out.getvalue()
    return run


def test_cli_create_list_and_restore_check(cli, dest):
    code, text = cli("list")
    assert code == 0 and "No backups" in text
    code, text = cli("create")
    assert code == 0 and "Backup created:" in text and "not encrypted" in text
    assert "browser profiles (login cookies) (1)" in text
    [archive] = backup.archives_in(dest)
    code, text = cli("list")
    assert code == 0 and archive.name in text and "manifest ok" in text
    code, text = cli("restore-check")
    assert code == 0 and f"restore-check {archive.name}: OK" in text
    assert "integrity ok" in text and "memory files: 1, projects: 1, task rows: 2" in text
    code, text = cli("restore-check", archive.name)
    assert code == 0 and "Live data was not touched" in text


def test_cli_restore_check_failure_returns_1(cli, dest, tmp_path):
    cli("create")
    [archive] = backup.archives_in(dest)
    bad = tmp_path / "tampered.tar.gz"
    _rewrite(archive, bad, change={"profile/SOUL.md": b"Be BRIEF."})
    code, text = cli("restore-check", str(bad))
    assert code == 1 and "FAILED" in text and "checksum does not match" in text


def test_cli_refuses_a_destination_in_the_repo(cli, cfg):
    target = REPO_ROOT / "backups-never-created"
    (cfg / "local.yaml").write_text(f"backup_file:\n  destination: {json.dumps(str(target))}\n", encoding="utf-8")
    code, text = cli("create")
    assert code == 1 and "Backup error: refusing backup destination" in text
    assert not target.exists()
