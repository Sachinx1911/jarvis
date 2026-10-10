"""In-memory GoogleClient for tests. Never touches the network.

`drop_writes=True` simulates a write that reports success but is not stored, so tests
can prove the verifiers catch it.
"""

from __future__ import annotations

import itertools
from datetime import datetime

from jarvis.connectors.google.client import GoogleError


class FakeGoogleClient:
    def __init__(self, events: list[dict] | None = None, messages: list[dict] | None = None,
                 drop_writes: bool = False, fail: bool = False):
        self.events: dict[str, dict] = {e["id"]: dict(e) for e in (events or [])}
        self.messages: dict[str, dict] = {m["id"]: dict(m) for m in (messages or [])}
        self.drafts: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.drop_writes = drop_writes
        self.fail = fail
        self._ids = itertools.count(1)

    def _check(self) -> None:
        if self.fail:
            raise GoogleError("fake network failure")

    # ---- Calendar ----
    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime, max_results: int = 25) -> list[dict]:
        self._check()
        out = []
        for e in self.events.values():
            start = datetime.fromisoformat(e["start"]["dateTime"])
            if time_min <= start < time_max:
                out.append(dict(e))
        out.sort(key=lambda e: datetime.fromisoformat(e["start"]["dateTime"]))
        return out[:max_results]

    def insert_event(self, calendar_id: str, body: dict) -> dict:
        self._check()
        event = dict(body, id=f"evt{next(self._ids)}", htmlLink="https://calendar.example/event")
        if not self.drop_writes:
            self.events[event["id"]] = event
        return dict(event)

    def get_event(self, calendar_id: str, event_id: str) -> dict | None:
        self._check()
        e = self.events.get(event_id)
        return dict(e) if e else None

    # ---- Gmail ----
    def search_messages(self, query: str, max_results: int = 10) -> list[dict]:
        self._check()
        words = [w.lower() for w in query.split() if ":" not in w]
        out = []
        for m in self.messages.values():
            hay = " ".join(str(m.get(k, "")) for k in ("from", "subject", "body", "snippet")).lower()
            if all(w in hay for w in words):
                out.append({k: v for k, v in m.items() if k != "body"})
        return out[:max_results]

    def get_message(self, message_id: str) -> dict | None:
        self._check()
        m = self.messages.get(message_id)
        return dict(m) if m else None

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        self._check()
        draft = {"id": f"draft{next(self._ids)}", "message_id": f"msg{next(self._ids)}", "to": to, "subject": subject,
                 "body": body}
        if not self.drop_writes:
            self.drafts[draft["id"]] = draft
        return dict(draft)

    def get_draft(self, draft_id: str) -> dict | None:
        self._check()
        d = self.drafts.get(draft_id)
        return dict(d) if d else None

    def send_message(self, to: str, subject: str, body: str) -> dict:
        self._check()
        msg = {"id": f"msg{next(self._ids)}", "threadId": "t1", "from": "me", "to": to, "subject": subject,
               "body": body, "date": "", "snippet": body[:80], "labelIds": ["SENT"]}
        self.sent.append(msg)
        if not self.drop_writes:
            self.messages[msg["id"]] = msg
        return {"id": msg["id"], "threadId": msg["threadId"]}

    def ping(self) -> str:
        self._check()
        return "fake client OK"
