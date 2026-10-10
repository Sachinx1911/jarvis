"""The real GoogleClient on google-api-python-client.

Imported only when Google is connected, so Jarvis runs without the Google libraries.
Not exercised by the offline tests (no credentials exist yet); the fake covers the
tool logic and this file is kept thin: request, then normalize to the shapes in client.py.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from email.message import EmailMessage
from html import unescape

from jarvis.connectors.google.client import GoogleError

MAX_BODY_CHARS = 20000


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body(payload: dict) -> str:
    """Plain-text body; falls back to HTML with the tags stripped."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain)[:MAX_BODY_CHARS]
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", "\n".join(html), flags=re.S | re.I)
    return unescape(re.sub(r"<[^>]+>", " ", text))[:MAX_BODY_CHARS]


def _raw(to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GoogleApiClient:
    def __init__(self, credentials):
        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
        except ImportError as e:  # pragma: no cover - dependency missing
            raise GoogleError("google-api-python-client is not installed") from e
        self._HttpError = HttpError
        self.calendar = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self.gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def _run(self, request):
        try:
            return request.execute()
        except self._HttpError as e:
            if getattr(e, "status_code", None) == 404 or getattr(getattr(e, "resp", None), "status", None) == 404:
                return None
            raise GoogleError(f"Google API error: {getattr(e, 'reason', e)}") from e
        except Exception as e:  # network, refresh errors
            if type(e).__name__ == "RefreshError":
                raise GoogleError("Google login expired or was revoked; Sachin must run `jarvis google auth`") from e
            raise GoogleError(f"Google request failed: {type(e).__name__}") from e

    # ---- Calendar ----
    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime, max_results: int = 25) -> list[dict]:
        res = self._run(self.calendar.events().list(
            calendarId=calendar_id, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=max_results)) or {}
        return res.get("items", [])

    def insert_event(self, calendar_id: str, body: dict) -> dict:
        res = self._run(self.calendar.events().insert(calendarId=calendar_id, body=body, sendUpdates="none"))
        if not res:
            raise GoogleError("event was not created")
        return res

    def get_event(self, calendar_id: str, event_id: str) -> dict | None:
        res = self._run(self.calendar.events().get(calendarId=calendar_id, eventId=event_id))
        if res and res.get("status") == "cancelled":
            return None
        return res

    # ---- Gmail ----
    def _meta(self, message_id: str, full: bool = False) -> dict | None:
        req = self.gmail.users().messages().get(
            userId="me", id=message_id, format="full" if full else "metadata",
            **({} if full else {"metadataHeaders": ["From", "To", "Subject", "Date"]}))
        res = self._run(req)
        if not res:
            return None
        headers = (res.get("payload") or {}).get("headers", [])
        out = {"id": res["id"], "threadId": res.get("threadId", ""), "from": _header(headers, "From"),
               "to": _header(headers, "To"), "subject": _header(headers, "Subject"), "date": _header(headers, "Date"),
               "snippet": unescape(res.get("snippet", "")), "labelIds": res.get("labelIds", [])}
        if full:
            out["body"] = _body(res.get("payload") or {})
        return out

    def search_messages(self, query: str, max_results: int = 10) -> list[dict]:
        res = self._run(self.gmail.users().messages().list(userId="me", q=query, maxResults=max_results)) or {}
        out = []
        for ref in res.get("messages", []):
            meta = self._meta(ref["id"])
            if meta:
                out.append(meta)
        return out

    def get_message(self, message_id: str) -> dict | None:
        return self._meta(message_id, full=True)

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        res = self._run(self.gmail.users().drafts().create(
            userId="me", body={"message": {"raw": _raw(to, subject, body)}}))
        if not res:
            raise GoogleError("draft was not created")
        return {"id": res["id"], "message_id": (res.get("message") or {}).get("id", ""), "to": to, "subject": subject}

    def get_draft(self, draft_id: str) -> dict | None:
        res = self._run(self.gmail.users().drafts().get(userId="me", id=draft_id, format="metadata"))
        if not res:
            return None
        headers = ((res.get("message") or {}).get("payload") or {}).get("headers", [])
        return {"id": res["id"], "message_id": (res.get("message") or {}).get("id", ""),
                "to": _header(headers, "To"), "subject": _header(headers, "Subject")}

    def send_message(self, to: str, subject: str, body: str) -> dict:
        res = self._run(self.gmail.users().messages().send(userId="me", body={"raw": _raw(to, subject, body)}))
        if not res:
            raise GoogleError("message was not sent")
        return {"id": res["id"], "threadId": res.get("threadId", "")}

    def ping(self) -> str:
        profile = self._run(self.gmail.users().getProfile(userId="me")) or {}
        # calendar.events scope: listing events works, calendars().get would need more.
        cal = self._run(self.calendar.events().list(calendarId="primary", maxResults=1)) or {}
        # Do not echo the address: it is personal data and this lands in logs.
        return f"Gmail OK ({profile.get('messagesTotal', '?')} messages), Calendar OK (time zone {cal.get('timeZone', '?')})"
