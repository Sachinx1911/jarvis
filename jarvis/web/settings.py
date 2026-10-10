"""Dashboard settings from config/web.yaml (+ config/local.yaml web_file) and the access token."""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.config import _merge, _read_yaml
from jarvis.paths import CONFIG_DIR, REPO_ROOT, local_config_path
from jarvis.secrets import get_secret, set_secret

TOKEN_NAME = "dashboard_token"
STATIC_DIR = REPO_ROOT / "dashboard" / "out"


@dataclass
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    approval_timeout_s: float = 300.0
    chat_idle_minutes: float = 120.0
    provider: str | None = None
    dev_origins: list[str] = field(default_factory=list)

    def origins(self) -> list[str]:
        """Browser origins allowed to call the API: the dashboard itself plus explicit dev origins."""
        own = [f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}", f"http://[::1]:{self.port}"]
        return own + [o.rstrip("/") for o in self.dev_origins if o and o != "*"]

    def hosts(self) -> list[str]:
        """Host header values accepted (blocks DNS rebinding)."""
        return [f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"]


def load_web_settings(config_dir: Path = CONFIG_DIR) -> WebSettings:
    data = _merge(_read_yaml(config_dir / "web.yaml"), _read_yaml(local_config_path(config_dir)).get("web_file", {}))
    s = WebSettings()
    s.host = str(data.get("host") or s.host)
    s.port = int(data.get("port") or s.port)
    s.approval_timeout_s = float(data.get("approval_timeout_s") or s.approval_timeout_s)
    s.chat_idle_minutes = float(data.get("chat_idle_minutes") or s.chat_idle_minutes)
    s.provider = data.get("provider") or None
    s.dev_origins = [str(o) for o in (data.get("dev_origins") or [])]
    return s


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def get_or_create_token(rotate: bool = False) -> str:
    """The random dashboard token, created on first start and kept in the OS secret store."""
    token = None if rotate else get_secret(TOKEN_NAME)
    if not token:
        token = secrets.token_urlsafe(32)
        set_secret(TOKEN_NAME, token)
    return token
