"""Local document wallet: passport, PAN, licence, insurance, PUC, warranties...

Records are P2: they stay on this machine and never go to the cloud model. Each record has a
type, holder (family member), optional expiry and reminder lead time, a masked number and a
link to a file Sachin adds himself under the workspace (Jarvis never downloads documents
from DigiLocker or other portals and never deletes the files).

Numbers are never stored in full: only the last 4 characters ("XXXX1234"). Full Aadhaar or
PAN numbers typed anywhere in a record (label, holder, notes) are masked on input, using the
privacy gate's patterns (UIDAI recommends masked Aadhaar; Aadhaar regulations bar keeping the
number beyond the purpose).

Income-tax deadlines come from config/india.yaml (tax.deadlines), never from code.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any

from jarvis.control.audit import AuditLog
from jarvis.india.text import mask_ids, mask_tail, scrub
from jarvis.proactive.reminders import ReminderStore

PRIVACY_CLASS = "P2"
DEFAULT_TYPES = ("passport", "pan", "aadhaar", "driving_licence", "insurance", "vehicle_puc", "vehicle_rc",
                 "warranty", "other")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS india_wallet (
    id INTEGER PRIMARY KEY,
    doc_type TEXT NOT NULL,
    holder TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    number_masked TEXT NOT NULL DEFAULT '',
    expiry TEXT,
    lead_days INTEGER NOT NULL,
    file_rel TEXT,
    notes TEXT NOT NULL DEFAULT '',
    reminder_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',     -- active | removed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS india_tax_reminders (
    key TEXT PRIMARY KEY,
    reminder_ids TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class WalletError(ValueError):
    pass


@dataclass
class WalletRecord:
    id: int
    doc_type: str
    holder: str
    label: str
    number_masked: str
    expiry: date | None
    lead_days: int
    file_rel: str | None
    notes: str
    reminder_ids: list[int] = field(default_factory=list)

    def line(self) -> str:
        name = self.label or self.doc_type.replace("_", " ")
        text = f"#{self.id} {name} ({self.doc_type}) - {self.holder}"
        if self.number_masked:
            text += f", no. {self.number_masked}"
        text += f", expires {self.expiry:%d %b %Y}" if self.expiry else ", no expiry"
        if self.file_rel:
            text += f", file {self.file_rel}"
        return text


def _record(row) -> WalletRecord:
    return WalletRecord(row[0], row[1], row[2], row[3], row[4], date.fromisoformat(row[5]) if row[5] else None,
                        row[6], row[7], row[8], json.loads(row[9] or "[]"))


_COLS = "id, doc_type, holder, label, number_masked, expiry, lead_days, file_rel, notes, reminder_ids"


class WalletStore:
    def __init__(self, conn: sqlite3.Connection, home: Path, tz: tzinfo, audit: AuditLog | None = None,
                 cfg: dict[str, Any] | None = None):
        self.db, self.home, self.tz, self.audit, self.cfg = conn, home, tz, audit, cfg or {}
        self.db.executescript(_SCHEMA)
        self.reminders = ReminderStore(conn, audit)

    @property
    def types(self) -> list[str]:
        return [str(t) for t in self.cfg.get("types") or DEFAULT_TYPES]

    @property
    def workspace(self) -> Path:
        return (self.home / "workspace").resolve()

    def _file(self, raw: str | None) -> tuple[str | None, list[str]]:
        if not raw:
            return None, []
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        if not p.is_relative_to(self.workspace):
            raise WalletError("the file must be inside the Jarvis workspace folder")
        notes = [] if p.exists() else [f"file not found yet: {p.relative_to(self.workspace)}"]
        return p.relative_to(self.workspace).as_posix(), notes

    def add(self, doc_type: str, holder: str, now: datetime, expiry: date | None = None, number: str = "",
            label: str = "", lead_days: int | None = None, file: str | None = None,
            notes: str = "") -> tuple[WalletRecord, list[str]]:
        """Returns (record, warnings). Full Aadhaar/PAN numbers anywhere are masked first."""
        doc_type = doc_type.strip().lower().replace(" ", "_")
        if doc_type not in self.types:
            raise WalletError(f"unknown document type {doc_type!r}; use one of: {', '.join(self.types)}")
        if not holder.strip():
            raise WalletError("whose document is it? (holder)")
        warnings: list[str] = []
        found: list[str] = []
        clean = {}
        for key, value in (("holder", holder), ("label", label), ("notes", notes)):
            masked, kinds = mask_ids(value)
            found += kinds
            clean[key] = scrub(masked).strip()
        if number:
            warnings.append("number stored masked (last 4 only)")
        if found:
            warnings.append(f"masked a full {', '.join(sorted(set(found)))} number in the text")
        file_rel, file_notes = self._file(file)
        warnings += file_notes
        lead = int(lead_days if lead_days is not None else self.cfg.get("default_lead_days") or 30)
        cur = self.db.execute(
            "INSERT INTO india_wallet (doc_type, holder, label, number_masked, expiry, lead_days, file_rel, notes, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_type, clean["holder"], clean["label"], mask_tail(number), expiry.isoformat() if expiry else None,
             lead, file_rel, clean["notes"], now.isoformat(timespec="seconds")))
        self.db.commit()
        rec = self.get(cur.lastrowid)  # type: ignore[arg-type]
        assert rec is not None
        self._schedule(rec, now)
        if self.audit:
            self.audit.write("india_wallet_added", record_id=rec.id, doc_type=doc_type, masked=sorted(set(found)))
        return self.get(rec.id), warnings  # type: ignore[return-value]

    def _schedule(self, rec: WalletRecord, now: datetime) -> None:
        if not rec.expiry:
            return
        hour = int(self.cfg.get("reminder_hour") or 9)
        name = rec.label or rec.doc_type.replace("_", " ")
        text = f"{name} of {rec.holder} expires on {rec.expiry:%d %b %Y}: time to renew [wallet #{rec.id}]"
        ids = []
        for day in sorted({rec.expiry - timedelta(days=rec.lead_days), rec.expiry}):
            at = datetime.combine(day, time(hour), self.tz)
            if at > now:
                ids.append(self.reminders.add(text, at, source="india_wallet", now=now).id)
        self.db.execute("UPDATE india_wallet SET reminder_ids=? WHERE id=?", (json.dumps(ids), rec.id))
        self.db.commit()

    def get(self, rid: int) -> WalletRecord | None:
        row = self.db.execute(f"SELECT {_COLS} FROM india_wallet WHERE id=? AND status='active'", (rid,)).fetchone()
        return _record(row) if row else None

    def list(self) -> list[WalletRecord]:
        rows = self.db.execute(f"SELECT {_COLS} FROM india_wallet WHERE status='active'").fetchall()
        return sorted((_record(r) for r in rows), key=lambda r: (r.expiry or date.max, r.id))

    def expiring(self, today: date, days: int) -> list[WalletRecord]:
        return [r for r in self.list() if r.expiry and r.expiry <= today + timedelta(days=days)]

    def remove(self, rid: int) -> bool:
        """Removes the record and its reminders. The linked file is left untouched."""
        rec = self.get(rid)
        if not rec:
            return False
        for r in rec.reminder_ids:
            self.reminders.cancel(r)
        self.db.execute("UPDATE india_wallet SET status='removed' WHERE id=?", (rid,))
        self.db.commit()
        if self.audit:
            self.audit.write("india_wallet_removed", record_id=rid)
        return True

    # ---- tax deadlines (from config) ----

    def schedule_tax_reminders(self, tax_cfg: dict[str, Any], now: datetime) -> list[str]:
        """Reminders for every future deadline in config (once each). Returns the names scheduled."""
        lead = int(tax_cfg.get("lead_days") or 7)
        hour = int(self.cfg.get("reminder_hour") or 9)
        done = []
        for item in tax_cfg.get("deadlines") or []:
            if not isinstance(item, dict) or not item.get("name") or not item.get("date"):
                continue
            due = item["date"] if isinstance(item["date"], date) else date.fromisoformat(str(item["date"]))
            key = f"{item['name']}|{due.isoformat()}"
            if self.db.execute("SELECT 1 FROM india_tax_reminders WHERE key=?", (key,)).fetchone():
                continue
            ids = []
            for day in sorted({due - timedelta(days=lead), due}):
                at = datetime.combine(day, time(hour), self.tz)
                if at > now:
                    ids.append(self.reminders.add(f"Tax deadline {due:%d %b %Y}: {item['name']}", at,
                                                  source="india_tax", now=now).id)
            if not ids:
                continue
            self.db.execute("INSERT INTO india_tax_reminders (key, reminder_ids, created_at) VALUES (?,?,?)",
                            (key, json.dumps(ids), now.isoformat(timespec="seconds")))
            done.append(str(item["name"]))
        self.db.commit()
        return done
