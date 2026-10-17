"""File tools inside allowed folders only (PLAN.md 11.2).

Every path goes through Path.resolve() and must stay inside an allowed root. Secret
locations (.ssh, .aws, .env files, key files, credential stores) are T4: never touched,
and the attempt is logged. Deleting moves the file into the workspace .trash folder.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path, PureWindowsPath

from jarvis.core.shruti import shruti_reason

MAX_READ_CHARS = 20000
MAX_WRITE_CHARS = 200_000

_BLOCKED_NAMES = {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", ".netrc", ".pgpass",
                  "id_rsa", "id_ed25519", "credentials", "keychains", "keychain"}
_BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".keychain", ".keychain-db"}


class PathBlocked(PermissionError):
    """A secret location: T4."""


class PathDenied(PermissionError):
    """Outside the allowed folders."""


def is_foreign_windows_path(raw: str) -> bool:
    """True on Mac/Linux for Windows-style absolute paths (C:\\..., C:/..., \\\\server\\share).
    POSIX would treat them as relative names inside the workspace; refuse them instead,
    so the same path is denied on every platform."""
    if os.name == "nt":
        return False
    return bool(PureWindowsPath(raw).drive) or raw.startswith("\\\\")


def is_secret_path(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    if any(p in _BLOCKED_NAMES for p in parts):
        return True
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.") or path.suffix.lower() in _BLOCKED_SUFFIXES


class PathPolicy:
    def __init__(self, roots: list[Path]):
        self.roots = [r.expanduser().resolve() for r in roots]

    def resolve(self, raw: str) -> Path:
        if is_foreign_windows_path(raw):
            raise PathDenied(f"{raw} is outside the allowed folders (a Windows path on this computer)")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.roots[0] / candidate  # relative paths are inside the workspace
        path = candidate.resolve()
        if is_secret_path(path) or is_secret_path(candidate):
            raise PathBlocked(f"{raw} is a protected secret location")
        # Shruti (PLAN.md 27.10): identity and law are never touched through a model's file tools.
        # Blocked like a secret location (T4): the attempt is audited and refused, read or write.
        why = shruti_reason(path) or shruti_reason(candidate)
        if why:
            raise PathBlocked(f"{raw} is {why}")
        if not any(path == r or path.is_relative_to(r) for r in self.roots):
            raise PathDenied(f"{raw} is outside the allowed folders")
        return path

    def show(self, path: Path) -> str:
        for r in self.roots:
            if path.is_relative_to(r):
                rel = path.relative_to(r).as_posix()
                return rel if r == self.roots[0] else f"{r.name}/{rel}"
        return str(path)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FileTools:
    def __init__(self, policy: PathPolicy):
        self.policy = policy
        self.policy.roots[0].mkdir(parents=True, exist_ok=True)

    @property
    def trash(self) -> Path:
        return self.policy.roots[0] / ".trash"

    # ---- T0 ----

    def read_file(self, args: dict) -> str:
        path = self.policy.resolve(args["path"])
        if not path.is_file():
            return f"No file {args['path']}."
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            return text[:MAX_READ_CHARS] + f"\n[... truncated, {len(text)} characters in total]"
        return text

    def list_folder(self, args: dict) -> str:
        path = self.policy.resolve(args.get("path") or ".")
        if not path.is_dir():
            return f"No folder {args.get('path')}."
        lines = []
        for child in sorted(path.iterdir()):
            if child.name == ".trash" or is_secret_path(child):
                continue
            kind = "folder" if child.is_dir() else f"{child.stat().st_size} bytes"
            lines.append(f"- {self.policy.show(child)} ({kind})")
        return "\n".join(lines) or "(empty folder)"

    # ---- T1: create only ----

    def write_file(self, args: dict) -> str:
        path = self.policy.resolve(args["path"])
        if path.exists():
            return f"{args['path']} already exists. Use overwrite_file to replace it."
        content = args["content"][:MAX_WRITE_CHARS]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Created {self.policy.show(path)} ({len(content)} characters)."

    def verify_write(self, args: dict) -> tuple[bool, str]:
        path = self.policy.resolve(args["path"])
        ok = path.is_file() and sha256_text(path.read_text(encoding="utf-8")) == sha256_text(args["content"][:MAX_WRITE_CHARS])
        return ok, "file exists with the expected content" if ok else "file missing or content differs"

    # ---- T2 ----

    def overwrite_file(self, args: dict) -> str:
        path = self.policy.resolve(args["path"])
        if not path.is_file():
            return f"No file {args['path']} to overwrite."
        backup = self._to_trash(path, copy=True)
        content = args["content"][:MAX_WRITE_CHARS]
        path.write_text(content, encoding="utf-8")
        return f"Replaced {self.policy.show(path)}; the old version is in {self.policy.show(backup)}."

    def _move_target(self, args: dict) -> tuple[Path, Path]:
        src = self.policy.resolve(args["source"])
        raw = args["destination"]
        dst = self.policy.resolve(raw)
        if dst.is_dir() or raw.endswith(("/", "\\")):
            dst = self.policy.resolve(str(dst / src.name))
        return src, dst

    def move_file(self, args: dict) -> str:
        src, dst = self._move_target(args)
        if not src.exists():
            return f"No file {args['source']}."
        if dst.exists():
            return f"{self.policy.show(dst)} already exists."
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved to {self.policy.show(dst)}."

    def moved_to(self, args: dict) -> Path:
        """Where move_file put the file (for provenance records)."""
        raw = args["destination"]
        dst = self.policy.resolve(raw)
        if dst.is_dir() or raw.endswith(("/", "\\")):
            dst = self.policy.resolve(str(dst / Path(args["source"]).name))
        return dst

    def verify_move(self, args: dict, before: tuple[Path, Path] | None = None) -> tuple[bool, str]:
        src, dst = before or self._move_target(args)
        ok = dst.exists() and not src.exists()
        return ok, "moved" if ok else "source still present or destination missing"

    # ---- T3 ----

    def delete_file(self, args: dict) -> str:
        path = self.policy.resolve(args["path"])
        if not path.is_file():
            return f"No file {args['path']}."
        moved = self._to_trash(path)
        return f"Deleted {args['path']} (kept in {self.policy.show(moved)})."

    def verify_delete(self, args: dict) -> tuple[bool, str]:
        path = self.policy.resolve(args["path"])
        return (not path.exists()), "file removed" if not path.exists() else "file still exists"

    def _to_trash(self, path: Path, copy: bool = False) -> Path:
        self.trash.mkdir(parents=True, exist_ok=True)
        dest = self.trash / f"{datetime.now():%Y%m%d-%H%M%S}-{path.name}"
        (shutil.copy2 if copy else shutil.move)(str(path), str(dest))
        return dest
