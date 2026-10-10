"""Bills from Gmail, through the Google connector's public client (jarvis/connectors/google).

Mail bodies are P2: they are read here and parsed with the fixed rules in bills.py, on this
machine. Nothing from a body goes to any model, and the body is not stored, only the fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from jarvis.connectors.google.client import GoogleError
from jarvis.india.bills import BillStore, extract_bill

NOT_CONNECTED = "Gmail is not connected (jarvis google auth)."


@dataclass
class ImportReport:
    seen: int = 0
    added: int = 0
    duplicates: int = 0
    not_bills: int = 0
    error: str | None = None
    bill_ids: list[int] = field(default_factory=list)

    def text(self) -> str:
        if self.error:
            return self.error
        return (f"Checked {self.seen} emails: {self.added} new bills/receipts, {self.duplicates} already known, "
                f"{self.not_bills} not bills.")


def default_client_factory() -> Callable[[], Any]:
    from jarvis.connectors.config import load_connectors_config
    from jarvis.connectors.registry import default_google_client

    return default_google_client(load_connectors_config())


def _received(raw: str, fallback: date) -> date:
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError):
        return fallback


def import_from_gmail(store: BillStore, client, bills_cfg: dict[str, Any], now: datetime) -> ImportReport:
    report = ImportReport()
    if client is None:
        report.error = NOT_CONNECTED
        return report
    query = str(bills_cfg.get("gmail_query") or "newer_than:60d (bill OR invoice OR \"due date\")")
    try:
        found = client.search_messages(query, int(bills_cfg.get("gmail_max") or 25))
    except GoogleError as e:
        report.error = f"Gmail: {e}"
        return report
    billers = bills_cfg.get("billers") or []
    for meta in found:
        report.seen += 1
        try:
            msg = client.get_message(meta["id"])
        except GoogleError as e:
            report.error = f"Gmail: {e}"
            break
        if not msg:
            continue
        draft = extract_bill(msg.get("body") or msg.get("snippet") or "", sender=msg.get("from", ""),
                             subject=msg.get("subject", ""), received=_received(msg.get("date", ""), now.date()),
                             billers=billers, today=now.date())
        if draft is None:
            report.not_bills += 1
            continue
        bill = store.add(draft, "gmail", msg["id"], now)
        if bill is None:
            report.duplicates += 1
        else:
            report.added += 1
            report.bill_ids.append(bill.id)
    if store.audit:
        store.audit.write("india_gmail_import", seen=report.seen, added=report.added, error=bool(report.error))
    return report
