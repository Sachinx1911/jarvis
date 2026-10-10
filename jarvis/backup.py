"""Local, dated backups of Jarvis's personal data: create, list, restore-check.

What goes in: memory/, profile/, skills/, projects/, workspace/, connectors/ and data/ under
JARVIS_HOME, plus config/local.yaml. SQLite databases are copied with the sqlite3 online
backup API (a consistent snapshot even while Jarvis is running), never by copying the open
file. manifest.json is the last member of every archive: format version, creation time,
code commit, and every file with its size and SHA-256.

What never goes in: data/browser/ (browser profiles hold login cookies), .env and .env.*,
key and certificate files (*.key, *.pem, ...), workspace/.trash, caches and downloaded
models, symlinks, and the backup folder itself. Secrets live in the OS keyring, not in
files, and are not exported.

Where: `destination` in config/backup.yaml (default ~/JarvisBackups). A destination inside
the code repository is refused: the repo is public. The folder is created owner-only (0700)
and archives are written 0600 (Mac/Linux). Archives are not encrypted yet; the final backup
location is open decision #10 in PLAN.md.

restore-check reads an archive and extracts it into a temporary folder only; it never
touches live data. Members with absolute paths, `..`, links or special files are rejected
before anything is extracted. The audit log gets names and counts, never file contents.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, BinaryIO

from jarvis.config import _merge, _read_yaml
from jarvis.control.audit import AuditLog
from jarvis.paths import CONFIG_DIR, REPO_ROOT
from jarvis.tools.files import is_secret_path

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_ARCHIVE_RE = re.compile(r"^jarvis-backup-(\d{8}-\d{6})(?:-(\d+))?\.tar\.gz$")

SOURCE_DIRS = ("memory", "profile", "skills", "projects", "workspace", "connectors", "data")
LOCAL_CONFIG_ARCNAME = "config/local.yaml"
MAIN_DB = "data/jarvis.db"

DEFAULTS: dict[str, Any] = {"destination": "~/JarvisBackups", "keep_last": 14, "exclude": []}

# Never backed up, whatever the config says (paths relative to JARVIS_HOME).
_EXCLUDED_TREES = {
    "data/browser": "browser profiles (login cookies)",
    "workspace/.trash": "workspace trash",
    "data/models": "downloaded models (cache)",
    "data/voice/tmp": "cache",
}
_EXCLUDED_FILES = {"data/app.lock": "runtime lock file"}
_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "node_modules"}
_CACHE_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
_SQLITE_HEADER = b"SQLite format 3\x00"
_SQLITE_SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


class BackupError(Exception):
    """A backup could not be made or checked; the message is safe to show and log."""


# ---- settings ----

@dataclass(frozen=True)
class BackupSettings:
    destination: str
    keep_last: int
    exclude: tuple[str, ...] = ()


def settings_from_dict(raw: dict[str, Any]) -> BackupSettings:
    dest = raw.get("destination")
    if not isinstance(dest, str) or not dest.strip():
        raise BackupError("backup destination is not set (destination in config/backup.yaml)")
    keep = raw.get("keep_last")
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        raise BackupError("keep_last must be a whole number of at least 1")
    exclude = raw.get("exclude") or []
    if isinstance(exclude, str):
        exclude = [exclude]
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise BackupError("exclude must be a list of path patterns")
    patterns = tuple(x.strip().replace("\\", "/").strip("/") for x in exclude if x.strip())
    return BackupSettings(dest.strip(), keep, patterns)


def load_backup_settings(config_dir: Path = CONFIG_DIR) -> BackupSettings:
    """config/backup.yaml merged with `backup_file:` from config/local.yaml."""
    override = _read_yaml(config_dir / "local.yaml").get("backup_file") or {}
    if not isinstance(override, dict):
        raise BackupError("backup_file in config/local.yaml must be a mapping")
    return settings_from_dict(_merge(_merge(DEFAULTS, _read_yaml(config_dir / "backup.yaml")), override))


# ---- destination ----

def _same_file(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _inside_repo(path: Path, repo_root: Path) -> bool:
    repo = repo_root.resolve()
    if path == repo or path.is_relative_to(repo):
        return True
    if sys.platform in ("darwin", "win32"):  # file systems there are usually case-insensitive
        p, r = str(path).casefold(), str(repo).casefold()
        if p == r or p.startswith(r.rstrip(os.sep) + os.sep):
            return True
    try:
        repo_stat = repo.stat()
    except OSError:
        return False
    for candidate in (path, *path.parents):  # the repo reached another way (hard link, mount)
        try:
            if _same_file(candidate.stat(), repo_stat):
                return True
        except OSError:
            continue
    return False


def check_destination(raw: str | Path, repo_root: Path = REPO_ROOT) -> Path:
    """The resolved backup folder. Refuses relative paths and anything inside the code repo."""
    text = str(raw or "").strip()
    if not text:
        raise BackupError("backup destination is not set (destination in config/backup.yaml)")
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        raise BackupError(f"backup destination must be an absolute path or start with ~ (got {text!r})")
    real = path.resolve()
    if _inside_repo(real, repo_root):
        raise BackupError(f"refusing backup destination {real}: it is inside the code repository "
                          f"({repo_root.resolve()}), which is public. Choose a folder outside it.")
    return real


def _ensure_private_dir(dest: Path, warnings: list[str]) -> None:
    if dest.exists():
        if not dest.is_dir():
            raise BackupError(f"backup destination {dest} exists and is not a folder")
        if sys.platform != "win32":
            mode = stat.S_IMODE(dest.stat().st_mode)
            if mode & 0o077:
                warnings.append(f"{dest} can be opened by other users (mode {mode:03o}); "
                                f"to fix: chmod 700 \"{dest}\"")
        return
    dest.mkdir(parents=True, mode=0o700)
    if sys.platform != "win32":
        os.chmod(dest, 0o700)


# ---- archive names ----

def _archive_key(path: Path) -> tuple[str, int]:
    m = _ARCHIVE_RE.match(path.name)
    assert m
    return m.group(1), int(m.group(2) or 1)


def archives_in(dest: Path) -> list[Path]:
    """Jarvis archives in the folder (regular files with Jarvis's name pattern), oldest first."""
    if not dest.is_dir():
        return []
    found = [p for p in dest.iterdir()
             if _ARCHIVE_RE.match(p.name) and p.is_file() and not p.is_symlink()]
    return sorted(found, key=_archive_key)


def _free_name(dest: Path, stamp: str) -> Path:
    candidate = dest / f"jarvis-backup-{stamp}.tar.gz"
    n = 1
    while candidate.exists() or (dest / f".{candidate.name}.partial").exists():
        n += 1
        candidate = dest / f"jarvis-backup-{stamp}-{n}.tar.gz"
    return candidate


def find_archive(arg: str, dest: Path | None) -> Path:
    """'latest' = newest archive in the destination; otherwise a path or a file name in it."""
    if arg == "latest":
        found = archives_in(dest) if dest else []
        if not found:
            raise BackupError(f"no backups in {dest}")
        return found[-1]
    path = Path(arg).expanduser()
    if not path.is_absolute() and not path.exists() and dest is not None:
        path = dest / arg
    if not path.is_file():
        raise BackupError(f"archive not found: {arg}")
    return path.resolve()


# ---- create ----

@dataclass
class _Plan:
    files: list[tuple[str, Path]] = field(default_factory=list)
    databases: list[tuple[str, Path]] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1


def _exclusion(rel: str, is_dir: bool, extra: tuple[str, ...]) -> str | None:
    for tree, reason in _EXCLUDED_TREES.items():
        if rel == tree or rel.startswith(tree + "/"):
            return reason
    name = rel.rsplit("/", 1)[-1]
    if is_secret_path(Path(rel)) or (name.lower().startswith("client_secret") and name.lower().endswith(".json")):
        return "secret files (.env, keys, certificates)"
    if is_dir and name in _CACHE_DIRS:
        return "cache"
    if not is_dir:
        if rel in _EXCLUDED_FILES:
            return _EXCLUDED_FILES[rel]
        if name.lower() in _CACHE_FILES or name.endswith(".pyc"):
            return "cache"
    if any(fnmatch.fnmatch(rel, pattern) for pattern in extra):
        return "excluded in config"
    return None


def _sqlite_side_file(path: Path) -> bool:
    """-wal/-shm/-journal next to a database: the snapshot already contains their data."""
    for suffix in _SQLITE_SIDE_SUFFIXES:
        if path.name.endswith(suffix) and (path.parent / path.name[: -len(suffix)]).is_file():
            return True
    return False


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _plan(home: Path, dest: Path, extra: tuple[str, ...]) -> _Plan:
    plan = _Plan()
    dest_stat = dest.stat()

    def is_dest(path: Path) -> bool:
        try:
            return _same_file(path.stat(), dest_stat)
        except OSError:
            return False

    for top in SOURCE_DIRS:
        root = home / top
        if root.is_symlink():
            plan.warnings.append(f"{top}/ is a symlink and was not backed up (links are never followed)")
            continue
        if not root.is_dir():
            continue
        if is_dest(root):
            plan.skip("backup folder")
            continue
        for dirpath, dirnames, filenames in os.walk(root):  # followlinks=False
            base = Path(dirpath)
            rel_base = base.relative_to(home).as_posix()
            kept = []
            for d in sorted(dirnames):
                full, rel = base / d, f"{rel_base}/{d}"
                if full.is_symlink():
                    plan.skip("symlinks")
                elif is_dest(full):
                    plan.skip("backup folder")
                elif reason := _exclusion(rel, True, extra):
                    plan.skip(reason)
                else:
                    kept.append(d)
            dirnames[:] = kept
            for name in sorted(filenames):
                full, rel = base / name, f"{rel_base}/{name}"
                try:
                    mode = full.lstat().st_mode
                except OSError as e:
                    plan.warnings.append(f"{rel}: cannot be read ({e.strerror or e})")
                    continue
                if stat.S_ISLNK(mode):
                    plan.skip("symlinks")
                elif not stat.S_ISREG(mode):
                    plan.skip("special files")
                elif reason := _exclusion(rel, False, extra):
                    plan.skip(reason)
                elif _sqlite_side_file(full):
                    plan.skip("database journal files (inside the snapshot)")
                elif "\\" in name:
                    plan.warnings.append(f"{rel}: a backslash in the file name is not portable; skipped")
                elif _is_sqlite(full):
                    plan.databases.append((rel, full))
                else:
                    plan.files.append((rel, full))
    return plan


def _snapshot_sqlite(src: Path, dst: Path) -> None:
    """Online backup API: a consistent copy even while another connection writes."""
    source = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)  # all pages in one step, under one read lock
        finally:
            target.close()
    finally:
        source.close()


class _HashingReader:
    """Hashes exactly the bytes tarfile reads, so the manifest matches the archive."""

    def __init__(self, f: BinaryIO):
        self._f = f
        self._h = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._f.read(size)
        self._h.update(data)
        return data

    def hexdigest(self) -> str:
        return self._h.hexdigest()


def _tarinfo(name: str, size: int, mtime: float) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = int(mtime)
    info.mode = 0o600
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _add_file(tar: tarfile.TarFile, rel: str, f: BinaryIO, mtime: float | None = None) -> dict[str, Any]:
    st = os.fstat(f.fileno())
    info = _tarinfo(rel, st.st_size, st.st_mtime if mtime is None else mtime)
    reader = _HashingReader(f)
    try:
        tar.addfile(info, reader)  # reads exactly st_size bytes (a growing log is cut at that size)
    except OSError as e:
        raise BackupError(f"{rel} changed while it was being backed up; run create again ({e})") from e
    return {"path": rel, "size": info.size, "sha256": reader.hexdigest()}


def _git_commit(repo_root: Path) -> str | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True,
                              timeout=10, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = done.stdout.strip()
    return sha if done.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None


@dataclass
class CreateResult:
    path: Path
    files: int
    data_bytes: int
    archive_bytes: int
    databases: list[str]
    excluded: dict[str, int]
    pruned: list[str]
    warnings: list[str]


def create_backup(home: Path, settings: BackupSettings, audit: AuditLog | None = None,
                  config_dir: Path = CONFIG_DIR, repo_root: Path = REPO_ROOT,
                  now: datetime | None = None) -> CreateResult:
    """Write one dated archive of the personal data, then keep only the newest keep_last."""
    try:
        try:
            return _create(home, settings, audit, config_dir, repo_root, now or datetime.now().astimezone())
        except OSError as e:
            raise BackupError(f"backup failed ({e.strerror or e})") from e
    except BackupError as e:
        if audit:
            audit.write("backup_create", ok=False, destination=str(settings.destination), error=str(e))
        raise


def _create(home: Path, settings: BackupSettings, audit: AuditLog | None, config_dir: Path,
            repo_root: Path, now: datetime) -> CreateResult:
    home = home.expanduser().resolve()
    dest = check_destination(settings.destination, repo_root)
    warnings: list[str] = []
    _ensure_private_dir(dest, warnings)
    plan = _plan(home, dest, settings.exclude)
    warnings += plan.warnings
    if not (home / MAIN_DB).exists():
        warnings.append(f"no database at {MAIN_DB} yet; the archive has files only")

    final = _free_name(dest, now.strftime("%Y%m%d-%H%M%S"))
    partial = dest / f".{final.name}.partial"
    entries: list[dict[str, Any]] = []
    snapshots: list[str] = []
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as raw, \
                tempfile.TemporaryDirectory(prefix="jarvis-backup-") as tmp, \
                tarfile.open(fileobj=raw, mode="w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as tar:
            for i, (rel, src) in enumerate(plan.databases):
                snap = Path(tmp) / f"snapshot-{i}.db"
                try:
                    _snapshot_sqlite(src, snap)
                except sqlite3.Error as e:
                    if rel == MAIN_DB:
                        raise BackupError(f"database snapshot failed ({e}); if Jarvis crashed, start it once so "
                                          "SQLite can recover the database, then run create again") from e
                    warnings.append(f"{rel}: database snapshot failed ({e}); skipped")
                    continue
                with snap.open("rb") as f:
                    entries.append(_add_file(tar, rel, f, mtime=src.stat().st_mtime))
                snapshots.append(rel)
            sources = list(plan.files)
            local = config_dir / "local.yaml"
            if local.is_file() and not local.is_symlink():
                sources.append((LOCAL_CONFIG_ARCNAME, local))
            for rel, src in sources:
                try:
                    f = src.open("rb")
                except OSError as e:
                    warnings.append(f"{rel}: cannot be read ({e.strerror or e}); skipped")
                    continue
                with f:
                    entries.append(_add_file(tar, rel, f))
            entries.sort(key=lambda e: e["path"])
            manifest = {
                "format_version": FORMAT_VERSION,
                "created_at": now.isoformat(timespec="seconds"),
                "code_commit": _git_commit(repo_root),
                "platform": sys.platform,
                "files": entries,
                "total_bytes": sum(e["size"] for e in entries),
                "sqlite_snapshots": snapshots,
                "excluded": dict(sorted(plan.excluded.items())),
            }
            data = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
            info = _tarinfo(MANIFEST_NAME, len(data), now.timestamp())
            tar.addfile(info, io.BytesIO(data))
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if sys.platform != "win32":
        os.chmod(final, 0o600)

    result = CreateResult(final, len(entries), sum(e["size"] for e in entries), final.stat().st_size,
                          snapshots, dict(sorted(plan.excluded.items())), [], warnings)
    if audit:
        audit.write("backup_create", ok=True, archive=final.name, destination=str(dest), files=result.files,
                    data_bytes=result.data_bytes, archive_bytes=result.archive_bytes,
                    sqlite_snapshots=len(snapshots), excluded=result.excluded, warnings=len(warnings))
    result.pruned = prune(dest, settings.keep_last, audit, warnings)
    return result


def prune(dest: Path, keep_last: int, audit: AuditLog | None = None,
          warnings: list[str] | None = None) -> list[str]:
    """Delete Jarvis archives in this folder beyond the newest keep_last. Nothing else is touched."""
    if keep_last < 1:
        raise BackupError("keep_last must be at least 1")
    removed: list[str] = []
    for path in archives_in(dest)[:-keep_last]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError as e:
            if warnings is not None:
                warnings.append(f"could not remove old backup {path.name}: {e.strerror or e}")
    if audit and removed:
        audit.write("backup_prune", destination=str(dest), keep_last=keep_last, removed=removed)
    return removed


# ---- manifest ----

def _parse_manifest(data: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BackupError(f"manifest.json is not valid JSON ({e})") from e
    if not isinstance(manifest, dict) or not isinstance(manifest.get("format_version"), int):
        raise BackupError("manifest.json has no format_version")
    if manifest["format_version"] > FORMAT_VERSION:
        raise BackupError(f"manifest format {manifest['format_version']} is newer than this Jarvis "
                          f"understands ({FORMAT_VERSION}); update the code first")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise BackupError("manifest.json has no file list")
    for entry in files:
        if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and isinstance(entry.get("size"), int) and not isinstance(entry.get("size"), bool)
                and isinstance(entry.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise BackupError("manifest.json has a malformed file entry")
    return manifest


def read_manifest(archive: Path) -> dict[str, Any]:
    """Only the manifest, streaming through the archive (it is the last member)."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                if member.name == MANIFEST_NAME:
                    if not member.isreg() or member.size > MAX_MANIFEST_BYTES:
                        raise BackupError("manifest.json is not a plain file or is too large")
                    f = tar.extractfile(member)
                    assert f is not None
                    return _parse_manifest(f.read())
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        raise BackupError(f"archive cannot be read ({e})") from e
    raise BackupError("no manifest.json in the archive")


# ---- list ----

@dataclass
class ArchiveInfo:
    path: Path
    size: int
    created: str
    files: int | None
    manifest_ok: bool
    note: str = ""


def list_backups(dest: Path) -> list[ArchiveInfo]:
    """Archives in the destination, newest first."""
    out = []
    for path in reversed(archives_in(dest)):
        stamp = datetime.strptime(_archive_key(path)[0], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        try:
            manifest = read_manifest(path)
            out.append(ArchiveInfo(path, path.stat().st_size, stamp, len(manifest["files"]), True))
        except BackupError as e:
            out.append(ArchiveInfo(path, path.stat().st_size, stamp, None, False, str(e)))
    return out


# ---- restore-check ----

def _unsafe_name(name: str) -> str | None:
    if not name or "\x00" in name:
        return "empty name"
    if "\\" in name:
        return "backslash in the path"
    if name.startswith("/") or PureWindowsPath(name).drive:
        return "absolute path"
    parts = name.split("/")
    if ".." in parts:
        return "parent-directory (..) path"
    if any(p in ("", ".") for p in parts):
        return "irregular path"
    return None


def _unsafe_member(member: tarfile.TarInfo) -> str | None:
    if reason := _unsafe_name(member.name):
        return reason
    if member.issym() or member.islnk():
        return "link"
    if not (member.isreg() or member.isdir()):
        return "special file"
    return None


@dataclass
class CheckReport:
    archive: Path
    problems: list[str] = field(default_factory=list)
    files_checked: int = 0
    databases: dict[str, str] = field(default_factory=dict)  # archive path -> "ok" or the first error
    memory_files: int = 0
    projects: int = 0
    tasks: int | None = None
    created_at: str | None = None
    code_commit: str | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def restore_check(archive: Path, audit: AuditLog | None = None, tmp_root: Path | None = None) -> CheckReport:
    """Verify an archive in a temporary folder: checksums, database integrity, counts.

    Live data is never read or written (only the audit log gets one line)."""
    report = CheckReport(archive)
    try:
        _check(archive, report, tmp_root)
    except BackupError as e:
        report.problems.append(str(e))
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        report.problems.append(f"archive cannot be read ({e})")
    if audit:
        audit.write("backup_restore_check", archive=archive.name, ok=report.ok, problems=len(report.problems),
                    files_checked=report.files_checked, databases=report.databases,
                    memory_files=report.memory_files, projects=report.projects, tasks=report.tasks)
    return report


def _check(archive: Path, report: CheckReport, tmp_root: Path | None) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        unsafe = [f"{m.name!r} ({why})" for m in members if (why := _unsafe_member(m))]
        if unsafe:
            raise BackupError("unsafe archive members, nothing was extracted: " + "; ".join(unsafe[:5]))
        names = [m.name for m in members if m.isreg()]
        if len(names) != len(set(names)):
            raise BackupError("the archive has duplicate member names, nothing was extracted")
        manifest_member = next((m for m in members if m.name == MANIFEST_NAME and m.isreg()), None)
        if manifest_member is None:
            raise BackupError("no manifest.json in the archive")
        if manifest_member.size > MAX_MANIFEST_BYTES:
            raise BackupError("manifest.json is too large")
        f = tar.extractfile(manifest_member)
        assert f is not None
        manifest = _parse_manifest(f.read())
        report.created_at = manifest.get("created_at")
        report.code_commit = manifest.get("code_commit")
        expected = {e["path"]: e for e in manifest["files"]}
        bad = [p for p in expected if _unsafe_name(p)]
        if bad:
            raise BackupError(f"the manifest lists unsafe paths: {bad[:3]!r}")

        with tempfile.TemporaryDirectory(prefix="jarvis-restore-check-", dir=tmp_root) as tmp:
            root = Path(tmp).resolve()
            needed = sum(e["size"] for e in expected.values())
            if shutil.disk_usage(root).free < needed:
                raise BackupError(f"not enough free space in {root.parent} to check {needed} bytes")
            seen: set[str] = set()
            for member in members:
                if not member.isreg() or member.name == MANIFEST_NAME:
                    continue
                entry = expected.get(member.name)
                if entry is None:
                    report.problems.append(f"{member.name}: in the archive but not in the manifest")
                    continue
                seen.add(member.name)
                if member.size != entry["size"]:
                    report.problems.append(f"{member.name}: size differs from the manifest")
                    continue
                target = root.joinpath(*member.name.split("/"))
                if not target.parent.resolve().is_relative_to(root):
                    report.problems.append(f"{member.name}: would land outside the check folder")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    digest = _extract_hashing(tar, member, target)
                except FileExistsError:
                    report.problems.append(f"{member.name}: collides with another member on this file system")
                    continue
                report.files_checked += 1
                if digest != entry["sha256"]:
                    report.problems.append(f"{member.name}: checksum does not match the manifest")
            for path in sorted(expected.keys() - seen):
                report.problems.append(f"{path}: listed in the manifest but missing from the archive")
            _check_databases(root, manifest, report)
            _count(root, report)


def _extract_hashing(tar: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> str:
    src = tar.extractfile(member)
    assert src is not None
    digest = hashlib.sha256()
    with target.open("xb") as out:  # "x": never overwrite anything
        while chunk := src.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _check_databases(root: Path, manifest: dict[str, Any], report: CheckReport) -> None:
    rels = list(manifest.get("sqlite_snapshots") or [])
    if not rels and (root / MAIN_DB).is_file():
        rels = [MAIN_DB]
    for rel in rels:
        if not isinstance(rel, str) or _unsafe_name(rel):
            report.problems.append("the manifest lists an unsafe database path")
            continue
        path = root.joinpath(*rel.split("/"))
        if not path.is_file():
            report.problems.append(f"{rel}: database missing from the archive")
            continue
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            rows = [str(r[0]) for r in conn.execute("PRAGMA integrity_check").fetchall()]
            report.databases[rel] = "ok" if rows == ["ok"] else (rows[0] if rows else "no result")
            if rows != ["ok"]:
                report.problems.append(f"{rel}: integrity_check failed ({report.databases[rel]})")
            if rel == MAIN_DB and conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks'").fetchone():
                report.tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        except sqlite3.DatabaseError as e:
            report.databases[rel] = f"error: {e}"
            report.problems.append(f"{rel}: cannot be opened as a database ({e})")
        finally:
            conn.close()


def _count(root: Path, report: CheckReport) -> None:
    memory = root / "memory"
    if memory.is_dir():
        report.memory_files = sum(1 for p in memory.rglob("m-*.md")
                                  if ".trash" not in p.relative_to(memory).parts)
    projects = root / "projects"
    if projects.is_dir():
        report.projects = sum(1 for p in projects.iterdir() if (p / "PROJECT.md").is_file())


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    size = n / 1024
    for unit in ("KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

