"""Egress control for tainted sessions (prompt-injection defense, research notes P0 #4).

Once a session or agent has read untrusted outside text (web, mail, calendar invites, files
with web provenance), the model may be steered into leaking data through a URL: a page asks it
to fetch https://allowed.test/?d=<secrets in base64>, or to show an image whose URL carries
the data. Rules, applied by the tool registry while the session is tainted:

- a URL (or search query) that carries a long or encoded payload is refused outright;
- a URL the user did not give (not in the user's own messages or the task goal) and that did
  not come back from web_search in this session/task needs the user's approval;
- once the quarantine reported an injection attempt ("hostile" session), even search-result
  URLs need approval.

Replies shown to the user never auto-load images: Markdown images and <img> tags are
replaced by a plain note (neutralize_reply), and links that carry encoded payloads are cut.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

URL_RE = re.compile(r"https?://[^\s)\]>\"'|`]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 32+ characters of base64/base64url, or 32+ hex digits: typical of smuggled data.
ENCODED_RE = re.compile(r"(?:[A-Za-z0-9+/_-]{32,}={0,2})|(?:[0-9a-fA-F]{32,})")
MAX_QUERY_CHARS = 120      # longer query strings are refused in tainted sessions
MAX_SEARCH_QUERY_CHARS = 300
SEARCH_URL_PREFIX = "    url: "  # the line format web_search results use (tools/catalog.py)


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text or "")]


def looks_encoded(s: str) -> bool:
    """A long run of base64/hex characters that is not a plain word or slug."""
    for m in ENCODED_RE.finditer(s):
        for seg in re.split(r"[-_]", m.group(0)):
            if len(seg) < 24:
                continue  # slugs like "best-laptops-under-60000-rupees" split into short words
            has_digit = any(c.isdigit() for c in seg)
            mixed_case = any(c.islower() for c in seg) and any(c.isupper() for c in seg)
            if has_digit or mixed_case or any(c in "+/=" for c in seg):
                return True
    return False


def suspicious_url(url: str) -> str | None:
    """Why a URL looks like a data-exfiltration carrier, or None."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return "the link cannot be parsed"
    if p.username or p.password:
        return "the link carries a user name or password"
    query = p.query + (("#" + p.fragment) if p.fragment else "")
    if len(query) > MAX_QUERY_CHARS:
        return f"the link has a long query string ({len(query)} characters)"
    # Only the query and fragment are checked for encoded data: paths legitimately hold commit
    # hashes and slugs. A link the user did not give needs approval anyway (check_url).
    if looks_encoded(urllib.parse.unquote_plus(query)):
        return "the link carries a long encoded string (base64 or hex)"
    if query.count("%") > 12:
        return "the link carries heavily percent-encoded data"
    return None


def suspicious_text(text: str) -> str | None:
    """For free-text arguments that leave the machine (e.g. a search query)."""
    if len(text) > MAX_SEARCH_QUERY_CHARS:
        return f"the text is unusually long ({len(text)} characters)"
    if looks_encoded(text):
        return "the text carries a long encoded string (base64 or hex)"
    return None


def _norm(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    path = p.path.rstrip("/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def search_result_urls(conn: sqlite3.Connection, task_id: str | None) -> set[str]:
    """URLs that web_search returned in this session or task (shared by all of a task's agents).

    Only the structured "url:" lines count; URLs inside snippet text are attacker-controlled."""
    if not task_id:
        return set()
    rows = conn.execute("SELECT result FROM tool_runs WHERE task_id=? AND tool='web_search' AND ok=1", (task_id,))
    out: set[str] = set()
    for (result,) in rows:
        for line in (result or "").splitlines():
            if line.startswith(SEARCH_URL_PREFIX):
                out.add(_norm(line[len(SEARCH_URL_PREFIX):].strip()))
    return out


@dataclass(frozen=True)
class Verdict:
    action: str  # "ok" | "ask" | "refuse"
    reason: str = ""


@dataclass
class EgressPolicy:
    """trusted_text: the user's own words (chat messages, task goal or work-order objective)."""
    conn: sqlite3.Connection
    trusted_text: Callable[[], list[str]] = field(default=lambda: [])

    def user_urls(self) -> set[str]:
        return {_norm(u) for t in self.trusted_text() for u in urls_in(t)}

    def check_url(self, url: str, tainted: bool, hostile: bool, task_id: str | None) -> Verdict:
        if not tainted:
            return Verdict("ok")
        bad = suspicious_url(url)
        if bad:
            return Verdict("refuse", f"{bad}; refused because this session has read untrusted outside text")
        n = _norm(url)
        if n in self.user_urls():
            return Verdict("ok")
        if hostile:
            return Verdict("ask", "a page tried to give the AI orders; every link not given by you needs approval")
        if n in search_result_urls(self.conn, task_id):
            return Verdict("ok")
        return Verdict("ask", "the link was not given by you and did not come from a web search; "
                              "it may come from untrusted text")

    def check_text(self, text: str, tainted: bool) -> Verdict:
        if not tainted:
            return Verdict("ok")
        bad = suspicious_text(text)
        if bad:
            return Verdict("refuse", f"{bad}; refused because this session has read untrusted outside text")
        return Verdict("ok")


# ---- replies shown to the user ----

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_MD_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
_HTML_IMG = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")


def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or "unknown site"
    except ValueError:
        return "unknown site"


def neutralize_reply(text: str) -> str:
    """Replies never auto-load images; links with encoded payloads are cut.

    Server-side, so the CLI, dashboard, Telegram and voice all get the safe text."""
    if not text:
        return text
    out = _MD_IMAGE.sub(lambda m: f"[image not shown: {m.group(1) or 'image'} ({_host(m.group(2))})]", text)
    out = _MD_IMAGE_REF.sub(lambda m: f"[image not shown: {m.group(1) or 'image'}]", out)
    out = _HTML_IMG.sub("[image not shown]", out)

    def link(m: re.Match) -> str:
        if suspicious_url(m.group(2)):
            return f"{m.group(1)} [link removed: it carried encoded data]"
        return m.group(0)

    out = _MD_LINK.sub(link, out)
    return out
