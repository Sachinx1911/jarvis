"""Google OAuth, "Desktop app" (installed-app) flow.

- The client secret JSON comes from Google Cloud Console; its path is set in
  config/local.yaml (connectors_file.google.client_secret_file) and it is never committed.
- Only the refresh token (plus scopes and the date it was issued) is kept, in the OS
  secret store under `google_oauth_token`. The short-lived access token stays in memory.
  This also keeps the item small: Windows Credential Manager caps a secret at 2,560 bytes.
- Nothing here prints or logs a token.
- If the OAuth app stays in "Testing", Google expires refresh tokens after 7 days. Set the
  app "In production" (personal use needs no verification, only a warning screen) and
  set google.oauth_app_status: production.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from jarvis.secrets import delete_secret, get_secret, set_secret

TOKEN_SECRET = "google_oauth_token"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",  # read and create events
    "https://www.googleapis.com/auth/gmail.readonly",   # search and read mail
    "https://www.googleapis.com/auth/gmail.compose",    # create drafts and send (send is T3, always asked)
]
TESTING_TOKEN_DAYS = 7


class GoogleAuthError(RuntimeError):
    pass


def client_secret_path(cfg: dict) -> Path | None:
    raw = ((cfg.get("google") or {}).get("client_secret_file") or "").strip()
    return Path(raw).expanduser() if raw else None


def _client_info(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GoogleAuthError(f"cannot read the OAuth client file: {e}") from e
    info = data.get("installed")
    if not isinstance(info, dict):
        raise GoogleAuthError('the OAuth client file must be a "Desktop app" client (key "installed")')
    return info


def load_token() -> dict[str, Any] | None:
    raw = get_secret(TOKEN_SECRET)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("refresh_token") else None


def save_token(refresh_token: str, scopes: list[str], client_id: str, issued: date | None = None) -> None:
    if not refresh_token:
        raise GoogleAuthError("Google returned no refresh token; remove Jarvis's access in your Google account "
                              "settings and run `jarvis google auth` again")
    blob = {"refresh_token": refresh_token, "scopes": sorted(scopes), "client_id": client_id,
            "issued": (issued or datetime.now(timezone.utc).date()).isoformat()}
    set_secret(TOKEN_SECRET, json.dumps(blob))


def forget_token() -> None:
    try:
        delete_secret(TOKEN_SECRET)
    except Exception:
        pass  # already gone


FlowFactory = Callable[[str, list[str]], Any]


def _default_flow(path: str, scopes: list[str]):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:  # pragma: no cover - dependency missing
        raise GoogleAuthError("google-auth-oauthlib is not installed") from e
    return InstalledAppFlow.from_client_secrets_file(path, scopes=scopes)


def run_oauth_flow(cfg: dict, flow_factory: FlowFactory | None = None) -> list[str]:
    """Open the browser for Google sign-in and keep the refresh token in the secret store.

    Only `jarvis google auth` calls this, i.e. only when Sachin runs it himself.
    Returns the granted scopes.
    """
    path = client_secret_path(cfg)
    if not path or not path.is_file():
        raise GoogleAuthError("set google.client_secret_file in config/local.yaml (connectors_file) to the "
                              "downloaded OAuth Desktop client JSON")
    info = _client_info(path)
    flow = (flow_factory or _default_flow)(str(path), SCOPES)
    # prompt=consent makes Google return a refresh token even on a repeat sign-in.
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent", access_type="offline")
    granted = list(getattr(creds, "scopes", None) or getattr(creds, "granted_scopes", None) or SCOPES)
    missing = [s for s in SCOPES if s not in granted]
    save_token(getattr(creds, "refresh_token", None) or "", granted, info.get("client_id", ""))
    if missing:
        raise GoogleAuthError("some permissions were not granted: " + ", ".join(s.rsplit("/", 1)[-1] for s in missing))
    return granted


def credentials(cfg: dict):
    """google.oauth2 Credentials built from the stored refresh token (no access token yet)."""
    token = load_token()
    if not token:
        raise GoogleAuthError("Google is not connected; Sachin must run `jarvis google auth`")
    path = client_secret_path(cfg)
    if not path or not path.is_file():
        raise GoogleAuthError("the OAuth client file is not set or missing (google.client_secret_file)")
    info = _client_info(path)
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as e:  # pragma: no cover - dependency missing
        raise GoogleAuthError("google-auth is not installed") from e
    return Credentials(None, refresh_token=token["refresh_token"], token_uri=info.get("token_uri", TOKEN_URI),
                       client_id=info.get("client_id"), client_secret=info.get("client_secret"),
                       scopes=token.get("scopes") or SCOPES)


def token_status(cfg: dict, today: date | None = None) -> tuple[bool, str]:
    """Is a token stored, does it have every scope, and when does it expire?"""
    token = load_token()
    if not token:
        return False, "not connected (run `jarvis google auth`)"
    today = today or datetime.now(timezone.utc).date()
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES if s not in (token.get("scopes") or [])]
    try:
        issued = date.fromisoformat(token.get("issued", ""))
    except ValueError:
        issued = None
    detail = f"token stored (issued {issued or 'unknown'})"
    ok = not missing
    if missing:
        detail += "; missing permissions: " + ", ".join(missing) + " (run `jarvis google auth` again)"
    status = ((cfg.get("google") or {}).get("oauth_app_status") or "testing").lower()
    if status != "production":
        if issued:
            expires = issued + timedelta(days=TESTING_TOKEN_DAYS)
            left = (expires - today).days
            if left < 0:
                ok = False
                detail += f"; EXPIRED on {expires} (app in Testing mode). Run `jarvis google auth`"
            else:
                detail += f"; app in Testing mode: expires about {expires} ({left} days left)"
        detail += ". Set the OAuth app 'In production' to stop the 7-day expiry"
    return ok, detail
