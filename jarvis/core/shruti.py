"""The shruti rule (PLAN.md 27.10): no model writes identity or law.

Shruti is what was heard and is fixed: Jarvis's identity (profile/SOUL.md), its laws and rules
(config/**, CLAUDE.md, PLAN.md) and the words its roles speak with (prompts/**). Smriti is what is
remembered and may change (memory/, core memory). A model route may read shruti through its system
prompt; it may never write it, through any tool, on any route. Only Sachin edits these files, by hand
or through git.

This module is the one place that says which paths are shruti. The file tools (jarvis/tools/files.py)
and the Coder's code_write ask it before every path they would touch, and tests/test_laws_shruti.py
checks that every store and tool write path goes through such a guard.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.paths import REPO_ROOT

# Patterns relative to the Jarvis repository root (code side) or to JARVIS_HOME (personal side).
# A pattern ending in "/**" names a whole folder.
SHRUTI_PATHS: tuple[str, ...] = (
    "profile/SOUL.md",   # identity (atman): under JARVIS_HOME
    "config/**",         # laws and rules: under the repository root
    "prompts/**",        # the words of the roles: under the repository root
    "CLAUDE.md",         # the working rules for Claude Code
    "PLAN.md",           # the plan and the laws themselves (section 27)
)


class ShrutiError(PermissionError):
    """A write to identity or law was attempted by a route that may not do it."""


def _home() -> Path:
    home = os.environ.get("JARVIS_HOME")
    return Path(home).expanduser().resolve() if home else REPO_ROOT


def shruti_roots(home: Path | None = None) -> tuple[Path, ...]:
    """The two places shruti files live: the repository and the personal home (often the same)."""
    h = (home or _home()).resolve()
    return tuple(dict.fromkeys((REPO_ROOT.resolve(), h)))


def _parts(path: Path) -> tuple[str, ...]:
    return tuple(p.lower() for p in path.parts)


def shruti_reason(path: Path | str, home: Path | None = None) -> str | None:
    """Why `path` is shruti, or None when it is not. Case-insensitive, so it holds on Windows and macOS
    where the file systems are case-insensitive. Does not touch the disk."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        return None  # relative paths are resolved by the caller's own policy first
    try:
        p = p.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    candidates = _parts(p)
    for root in shruti_roots(home):
        rp = _parts(root)
        if candidates[: len(rp)] != rp:
            continue
        rel = candidates[len(rp):]
        if not rel:
            continue
        for pattern in SHRUTI_PATHS:
            pat = tuple(x.lower() for x in pattern.split("/"))
            if pat[-1] == "**":
                if rel[: len(pat) - 1] == pat[:-1]:
                    return f"a protected law file (shruti: {pattern})"
            elif rel == pat:
                return f"a protected identity or law file (shruti: {pattern})"
    return None


def is_shruti(path: Path | str, home: Path | None = None) -> bool:
    return shruti_reason(path, home) is not None


def assert_not_shruti(path: Path | str, home: Path | None = None) -> None:
    """Raise ShrutiError when a model-driven write would land on identity or law (27.10)."""
    why = shruti_reason(path, home)
    if why:
        raise ShrutiError(f"{path} is {why}; only Sachin edits it, never a model")


__all__ = ["SHRUTI_PATHS", "ShrutiError", "assert_not_shruti", "is_shruti", "shruti_reason", "shruti_roots"]
