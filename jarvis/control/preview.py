"""Effect previews for approvals: what will change, where and how much (research 2026-10-10).

Approval prompts that show only a command get rubber-stamped. A preview states the effect:
a diff for overwrite, the target path and size for write/move, what goes to the trash for
delete, the exact calendar event, the email's recipient/subject/body, the exact URL with its
domain marked. `preview(tool, arguments)` never raises and never changes anything; it reads
files only inside the allowed folders (the same PathPolicy the file tools use) and redacts
secrets (P3) from what it shows.

Marking: text between [[ and ]] is the part to check (the dashboard shows it highlighted;
the terminal and Telegram show the brackets).
"""

from __future__ import annotations

import difflib
import sqlite3
import urllib.parse
from datetime import timedelta
from pathlib import Path
from typing import Callable

from jarvis.control.egress import suspicious_url, urls_in
from jarvis.privacy import redact_p3
from jarvis.tools.files import MAX_WRITE_CHARS, PathBlocked, PathDenied, PathPolicy

MAX_PREVIEW_CHARS = 2500
MAX_DIFF_LINES = 40
BODY_PREVIEW_CHARS = 400
CONTENT_HEAD_LINES = 6
DEFAULT_EVENT_MINUTES = 30  # same default as the calendar tool (connectors.yaml)


def mark(text: str) -> str:
    return f"[[{text}]]"


def _size(n_chars: int, text: str = "") -> str:
    n_bytes = len(text.encode("utf-8")) if text else n_chars
    return f"{n_chars} characters, {n_bytes} bytes" if text else f"{n_bytes} bytes"


def _head(text: str, lines: int = CONTENT_HEAD_LINES, chars: int = BODY_PREVIEW_CHARS) -> str:
    rows = text.splitlines()
    out = "\n".join("  | " + r for r in rows[:lines])
    if len(out) > chars:
        out = out[:chars] + " ..."
    if len(rows) > lines:
        out += f"\n  | ... ({len(rows) - lines} more lines)"
    return out


class _Files:
    def __init__(self, roots: list[Path] | None):
        self.policy = PathPolicy(roots) if roots else None

    def resolve(self, raw: str) -> tuple[Path | None, str]:
        """(path, shown name) or (None, why it is refused)."""
        if self.policy is None:
            return None, f"{raw} (allowed folders unknown here)"
        try:
            path = self.policy.resolve(raw)
        except PathBlocked:
            return None, f"{raw}: protected secret location, never allowed"
        except PathDenied:
            return None, f"{raw}: outside the allowed folders, will be refused"
        return path, self.policy.show(path)

    def root_name(self) -> str:
        return self.policy.roots[0].name if self.policy else "workspace"


def _write(args: dict, files: _Files) -> str:
    content = str(args.get("content", ""))[:MAX_WRITE_CHARS]
    path, shown = files.resolve(str(args.get("path", "")))
    lines = [f"Create new file: {mark(shown)}", f"Size: {_size(len(content), content)}"]
    if path is not None and path.exists():
        lines.append("Note: this file already exists, so the write will be refused (nothing changes).")
    elif path is not None and not path.parent.exists():
        lines.append(f"New folder will be created: {files.policy.show(path.parent) if files.policy else path.parent}")
    if content:
        lines += ["First lines:", _head(content)]
    return "\n".join(lines)


def _overwrite(args: dict, files: _Files) -> str:
    new = str(args.get("content", ""))[:MAX_WRITE_CHARS]
    path, shown = files.resolve(str(args.get("path", "")))
    lines = [f"Replace the content of: {mark(shown)}"]
    if path is None:
        return "\n".join(lines)
    if not path.is_file():
        lines.append("Note: no such file, so nothing will be replaced.")
        return "\n".join(lines)
    try:
        old = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        lines.append(f"(cannot read the current file: {e})")
        return "\n".join(lines)
    lines.append(f"Size: {_size(len(old), old)} now -> {_size(len(new), new)} after")
    lines.append(f"The old version is kept in {files.root_name()}/.trash.")
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "current", "new", lineterm="", n=2))
    if not diff:
        lines.append("No change: the new content is the same as the current file.")
        return "\n".join(lines)
    shown_diff = []
    for d in diff:
        if d.startswith(("---", "+++", "@@")):
            shown_diff.append(d)
        elif d.startswith("+"):
            shown_diff.append("+ " + d[1:])
        elif d.startswith("-"):
            shown_diff.append("- " + d[1:])
        else:
            shown_diff.append("  " + d[1:])
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    lines.append(f"Changes: {added} lines added, {removed} lines removed")
    if len(shown_diff) > MAX_DIFF_LINES:
        rest = len(shown_diff) - MAX_DIFF_LINES
        shown_diff = shown_diff[:MAX_DIFF_LINES] + [f"... ({rest} more diff lines)"]
    return "\n".join(lines + shown_diff)


def _move(args: dict, files: _Files) -> str:
    src, src_shown = files.resolve(str(args.get("source", "")))
    raw = str(args.get("destination", ""))
    dst, dst_shown = files.resolve(raw)
    if src is not None and dst is not None and (dst.is_dir() or raw.endswith(("/", "\\"))):
        dst, dst_shown = files.resolve(str(dst / src.name))
    lines = [f"Move: {mark(src_shown)}", f"  to: {mark(dst_shown)}"]
    if src is not None:
        if src.is_file():
            lines.append(f"Size: {_size(src.stat().st_size)}")
        else:
            lines.append("Note: the source file does not exist, so nothing will move.")
    if dst is not None and dst.exists():
        lines.append("Note: the destination already exists, so the move will be refused.")
    return "\n".join(lines)


def _delete(args: dict, files: _Files) -> str:
    path, shown = files.resolve(str(args.get("path", "")))
    lines = [f"Delete: {mark(shown)}"]
    if path is not None:
        if path.is_file():
            lines.append(f"Size: {_size(path.stat().st_size)}")
            lines.append(f"It is moved to {files.root_name()}/.trash (can be restored from there).")
        else:
            lines.append("Note: no such file, so nothing will be deleted.")
    return "\n".join(lines)


def url_line(url: str) -> str:
    """The URL with its domain marked, plus warnings."""
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = p.hostname or ""
    except ValueError:
        return f"URL: {url} (cannot be parsed)"
    if not host:
        return f"URL: {url} (no site in this link)"
    netloc = p.netloc
    i = netloc.lower().rfind(host.lower())
    marked = netloc[:i] + mark(netloc[i:i + len(host)]) + netloc[i + len(host):] if i >= 0 else netloc
    shown = urllib.parse.urlunsplit((p.scheme, "\x00", p.path, p.query, p.fragment)).replace("\x00", marked)
    out = [f"URL: {shown}", f"Site: {mark(host)}"]
    if p.scheme not in ("http", "https"):
        out.append(f"Note: {p.scheme or 'no'} scheme; only http(s) links are opened")
    bad = suspicious_url(url)
    if bad:
        out.append(f"WARNING: {bad}")
    return "\n".join(out)


def _open_url(args: dict, files: _Files) -> str:
    return "Open in the browser:\n" + url_line(str(args.get("url", "")))


def _calendar(args: dict, files: _Files, tz_name: str | None = None) -> str:
    from jarvis.connectors.timeparse import TimeParseError, get_tz, parse_iso

    minutes = DEFAULT_EVENT_MINUTES
    if tz_name is None:  # the calendar tool's own settings (config/connectors.yaml)
        try:
            from jarvis.connectors.config import load_connectors_config

            cfg = load_connectors_config()
            tz_name = cfg.get("timezone") or None
            minutes = int((cfg.get("google") or {}).get("default_event_minutes") or minutes)
        except Exception:
            pass
    title = str(args.get("title", ""))
    lines = ["New Google Calendar event (no invitations are sent):", f"  Title:    {mark(title)}"]
    try:
        start = parse_iso(str(args.get("start", "")), tz_name)
        end = (parse_iso(str(args["end"]), tz_name) if args.get("end")
               else start + timedelta(minutes=minutes))
        tz = get_tz(tz_name)
        s, e = start.astimezone(tz), end.astimezone(tz)
        same_day = s.date() == e.date()
        when = f"{s:%A %d %b %Y, %H:%M} to {e:%H:%M}" if same_day else f"{s:%A %d %b %Y, %H:%M} to {e:%A %d %b %Y, %H:%M}"
        lines.append(f"  When:     {mark(when)} ({tz_name or 'Asia/Kolkata'})")
        if not args.get("end"):
            lines.append(f"  (no end given: {minutes} minutes)")
        if end <= start:
            lines.append("  Note: the end is not after the start, so it will be refused.")
    except (TimeParseError, ValueError):
        lines.append(f"  When:     {args.get('start')!r} is not an exact time yet; it will be refused")
    if args.get("location"):
        lines.append(f"  Where:    {args['location']}")
    if args.get("description"):
        lines.append("  Notes:\n" + _head(str(args["description"])))
    return "\n".join(lines)


def _mail(args: dict, send: bool) -> str:
    to = str(args.get("to", ""))
    body = str(args.get("body", ""))
    head = "SEND this email now (cannot be unsent):" if send else "Save this email as a Gmail draft (not sent):"
    recipients = [r.strip() for r in to.replace(";", ",").split(",") if r.strip()]
    lines = [head, f"  To:      {', '.join(mark(r) for r in recipients) or '(nobody)'}",
             f"  Subject: {args.get('subject', '')}",
             f"  Body ({len(body)} characters):", _head(body, lines=8)]
    links = urls_in(body)
    if links:
        lines.append(f"  Links in the body: {len(links)}")
        lines += ["  " + url_line(u).replace("\n", "\n  ") for u in links[:3]]
    return "\n".join(lines)


def _browser_open(args: dict, files: _Files) -> str:
    return "Open in the isolated browser:\n" + url_line(str(args.get("url", "")))


def _code_write(args: dict, files: _Files) -> str:
    content = str(args.get("content", ""))
    return "\n".join([f"Write project file: {mark(str(args.get('path', '')))} (old version kept)",
                      f"Size: {_size(len(content), content)}", "First lines:", _head(content)])


def _reminder(args: dict, files: _Files) -> str:
    out = [f"New reminder: {mark(str(args.get('title', '')))}"]
    if args.get("due"):
        out.append(f"Due: {args['due']}")
    return "\n".join(out)


_PREVIEWS: dict[str, Callable[[dict, _Files], str]] = {
    "write_file": _write,
    "overwrite_file": _overwrite,
    "move_file": _move,
    "delete_file": _delete,
    "open_url": _open_url,
    "browser_open": _browser_open,
    "gmail_send": lambda a, f: _mail(a, send=True),
    "gmail_draft": lambda a, f: _mail(a, send=False),
    "code_write": _code_write,
    "reminder_create": _reminder,
}


def preview(tool: str, arguments: dict, roots: list[Path] | None = None, tz_name: str | None = None) -> str:
    """What running `tool` with `arguments` will change, as plain text ("" when there is no
    preview for this tool). Never raises."""
    try:
        files = _Files(roots)
        if tool == "calendar_create_event":
            text = _calendar(arguments, files, tz_name)
        elif tool in _PREVIEWS:
            text = _PREVIEWS[tool](arguments, files)
        else:
            return ""
    except Exception as e:  # a preview must never block or crash an approval
        return f"(no preview: {type(e).__name__})"
    text = redact_p3(text)[0]
    if len(text) > MAX_PREVIEW_CHARS:
        text = text[:MAX_PREVIEW_CHARS] + "\n... (preview cut here)"
    return text


def target_folder(tool: str, arguments: dict, roots: list[Path] | None) -> Path | None:
    """The folder a file tool writes into (for grouped approvals), or None."""
    raw = arguments.get("path") if tool != "move_file" else arguments.get("destination")
    if not isinstance(raw, str) or not roots:
        return None
    path, _ = _Files(roots).resolve(raw)
    if path is None:
        return None
    if tool == "move_file" and (path.is_dir() or raw.endswith(("/", "\\"))):
        return path
    return path.parent


def roots_for(conn: sqlite3.Connection) -> list[Path] | None:
    """The allowed file folders for the Jarvis home that owns this database (home/data/jarvis.db),
    read the same way as tools.catalog.file_roots. None when it cannot be told."""
    try:
        row = next((r for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
        if not row or not row[2]:
            return None
        db = Path(row[2])
        if db.parent.name != "data":
            return None
        home = db.parent.parent
        from jarvis.config import load_config

        allowed = ((load_config().tools or {}).get("files") or {}).get("allowed") or ["workspace"]
    except Exception:
        return None
    roots = []
    for raw in allowed:
        p = Path(raw).expanduser()
        roots.append(p if p.is_absolute() else home / p)
    return roots
