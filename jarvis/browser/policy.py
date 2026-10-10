"""Browser safety rules (PLAN.md 11.4): domain allowlist, site profiles, download checks.

Pure functions and small classes, no Playwright import, so everything here is testable offline.
"""

from __future__ import annotations

import re
import shutil
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import yaml

from jarvis.paths import CONFIG_DIR

URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")
SITE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")


class BrowserError(Exception):
    """A browser action failed or was blocked."""


class DownloadRejected(BrowserError):
    pass


def load_browser_config(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """config/browser.yaml merged with config/local.yaml -> browser_file."""
    return _load(config_dir, "browser.yaml", "browser_file")


def _load(config_dir: Path, name: str, local_key: str) -> dict[str, Any]:
    def read(p: Path) -> dict[str, Any]:
        if not p.exists():
            return {}
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    base = read(config_dir / name)
    override = read(config_dir / "local.yaml").get(local_key) or {}
    for k, v in override.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


# ---- domain allowlist ----

def _host(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    try:
        return parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return None


def normalize_domain(raw: str) -> str:
    """'https://www.Shop.example/x' -> 'www.shop.example'. Raises ValueError for junk or bare TLDs."""
    text = raw.strip().lower()
    host = _host(text) if "://" in text else text.split("/")[0].split(":")[0]
    host = (host or "").lstrip("*.").rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise ValueError(f"bad domain: {raw}") from e
    if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host) or host.startswith(".") or ".." in host:
        raise ValueError(f"bad domain: {raw}")
    return host


class DomainAllowlist:
    """A host is allowed if it equals an allowed domain or is a subdomain of one."""

    def __init__(self, domains: list[str] | tuple[str, ...] | set[str]):
        self.domains = frozenset(normalize_domain(d) for d in domains)

    def allows(self, url: str) -> bool:
        if url in ("about:blank", ""):
            return True
        host = _host(url)
        if not host:
            return False
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def __str__(self) -> str:
        return ", ".join(sorted(self.domains)) or "(none)"


def domains_from_text(text: str) -> list[str]:
    """Domains of the links in the user's own words (trusted input), e.g. the task goal."""
    out: list[str] = []
    for url in URL_RE.findall(text):
        try:
            d = normalize_domain(url.rstrip(".,;"))
        except ValueError:
            continue
        if d not in out:
            out.append(d)
    return out


# ---- site profiles (sites that need a login) ----

def profiles_root(home: Path) -> Path:
    return home / "data" / "browser"


def profile_dir(home: Path, site: str) -> Path:
    """<home>/data/browser/<site>/. The site is a plain name like 'shop.example'."""
    name = site.strip().lower()
    if not SITE_RE.fullmatch(name) or ".." in name:
        raise ValueError(f"bad site name: {site!r} (use something like shop.example)")
    path = profiles_root(home) / name
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        path.chmod(0o700)  # only the user's account may read the cookies
        profiles_root(home).chmod(0o700)
    return path


def list_profiles(home: Path) -> list[tuple[str, int]]:
    root = profiles_root(home)
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and SITE_RE.fullmatch(p.name):
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            out.append((p.name, size))
    return out


def wipe_profile(home: Path, site: str) -> bool:
    name = site.strip().lower()
    if not SITE_RE.fullmatch(name) or ".." in name:
        raise ValueError(f"bad site name: {site!r}")
    path = profiles_root(home) / name
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    return True


# ---- downloads ----

_MAGIC: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "zip": (b"PK\x03\x04", b"PK\x05\x06"),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "pptx": (b"PK\x03\x04",),
}
_TEXT_TYPES = {"txt", "csv", "json", "md"}


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "download"
    return base[:120]


def check_download(path: Path, allowed_types: list[str], max_bytes: int) -> str:
    """Return the file type, or raise DownloadRejected. The extension must be allowed AND the
    first bytes must match it (a renamed .exe is rejected)."""
    ext = path.suffix.lower().lstrip(".")
    allowed = {t.lower().lstrip(".") for t in allowed_types}
    if ext not in allowed:
        raise DownloadRejected(f"file type .{ext or '?'} is not allowed (allowed: {', '.join(sorted(allowed))})")
    size = path.stat().st_size
    if size > max_bytes:
        raise DownloadRejected(f"file is {size // 1024} KB, over the {max_bytes // 1024} KB limit")
    head = path.read_bytes()[:4096] if size else b""
    if ext in _TEXT_TYPES:
        if b"\x00" in head:
            raise DownloadRejected(f"file claims to be .{ext} but is not text")
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start < len(head) - 4:  # a multi-byte char cut at the 4 KB boundary is fine
                raise DownloadRejected(f"file claims to be .{ext} but is not UTF-8 text") from e
        return ext
    if not any(head.startswith(m) for m in _MAGIC.get(ext, ())):
        raise DownloadRejected(f"file content does not match .{ext}")
    return ext
