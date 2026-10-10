"""GoogleClient: the small surface Jarvis needs from Calendar and Gmail.

Tools depend on this interface only, so every tool and verifier is tested offline with
FakeGoogleClient, and the real API code stays in one file (api.py).

Shapes (plain dicts, so the fake and the real client agree):
  event    {"id", "summary", "start": {"dateTime"}, "end": {"dateTime"}, "location"?, "description"?,
            "attendees"?: [{"email"}], "htmlLink"?}   (Google's event resource, subset)
  message  {"id", "threadId", "from", "to", "subject", "date", "snippet", "body"?, "labelIds": [...]}
  draft    {"id", "message_id", "to", "subject"}
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class GoogleError(RuntimeError):
    pass


class GoogleClient(Protocol):
    # ---- Calendar ----
    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime,
                    max_results: int = 25) -> list[dict]: ...

    def insert_event(self, calendar_id: str, body: dict) -> dict: ...

    def get_event(self, calendar_id: str, event_id: str) -> dict | None: ...

    # ---- Gmail ----
    def search_messages(self, query: str, max_results: int = 10) -> list[dict]: ...

    def get_message(self, message_id: str) -> dict | None: ...

    def create_draft(self, to: str, subject: str, body: str) -> dict: ...

    def get_draft(self, draft_id: str) -> dict | None: ...

    def send_message(self, to: str, subject: str, body: str) -> dict: ...

    # ---- health ----
    def ping(self) -> str: ...
