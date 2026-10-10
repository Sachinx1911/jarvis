"""Bills, subscriptions and AutoPay tracker.

Extraction is deterministic and local (fixed English + Marathi rules), because the inputs are
mail bodies and SMS text (P2): they are never sent to a model. Only the extracted fields are
stored (biller, category, amount, dates, flags), never the message text. Aadhaar/PAN numbers
are masked and other secrets (OTPs, card numbers) withheld before any rule runs.

Jarvis never pays. See upi.py for the only payment-related thing it does: a hand-off link.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from jarvis.control.audit import AuditLog
from jarvis.india.text import find_amounts, find_dates, format_inr, scrub
from jarvis.proactive.reminders import ReminderStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS india_bills (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,            -- gmail | paste | manual
    source_ref TEXT NOT NULL,        -- gmail message id, or a hash of the pasted text
    biller TEXT NOT NULL,
    biller_key TEXT NOT NULL,
    category TEXT NOT NULL,
    kind TEXT NOT NULL,              -- bill | subscription | receipt
    amount_paise INTEGER,
    due_date TEXT,
    bill_date TEXT NOT NULL,
    status TEXT NOT NULL,            -- due | paid | ignored
    autopay INTEGER NOT NULL DEFAULT 0,
    period_hint TEXT,
    reminder_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (source, source_ref)
);
CREATE INDEX IF NOT EXISTS india_bills_biller ON india_bills(biller_key);
CREATE TABLE IF NOT EXISTS india_payees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    biller_key TEXT,
    vpa TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,      -- Sachin typed and confirmed it himself (CLI)
    UNIQUE (biller_key)
);
"""

# ---------------------------------------------------------------- rules

RECEIPT_WORDS = ("payment received", "payment successful", "successfully paid", "paid successfully",
                 "thank you for your payment", "thank you for the payment", "has been debited", "is debited",
                 "was debited", "transaction successful", "received your payment", "payment has been received",
                 "भरणा यशस्वी", "यशस्वीरित्या", "प्राप्त झाला", "भरणा प्राप्त", "रक्कम जमा")
AUTOPAY_WORDS = ("autopay", "auto pay", "auto-pay", "auto-debit", "auto debit", "e-mandate", "emandate", "mandate",
                 "standing instruction", "ऑटोपे", "ऑटो डेबिट")
SUBSCRIPTION_WORDS = ("subscription", "renewal", "renews", "will renew", "membership", "your plan",
                      "सदस्यता", "नूतनीकरण")
BILL_WORDS = ("bill", "invoice", "due date", "amount due", "payable", "statement", "premium due", "emi",
              "बिल", "देयक", "देय", "थकबाकी", "हप्ता")
DUE_BEFORE = ("due date", "due on", "due by", "is due", "pay by", "pay before", "last date", "payment due",
              "renews on", "renewal date", "will renew on", "renew on", "will be debited on", "debit on",
              "before", "देय तारीख", "देय दिनांक", "अंतिम तारीख", "शेवटची तारीख", "भरण्याची तारीख", "नूतनीकरण तारीख")
DUE_AFTER = ("पर्यंत", "पूर्वी")
AMOUNT_GOOD = ("amount due", "total amount due", "total due", "bill amount", "amount payable", "net payable",
               "payable", "total", "amount of", "premium", "रक्कम", "देय रक्कम", "एकूण", "बिलाची रक्कम")
CATEGORY_WORDS = [
    ("credit_card", ("credit card", "card statement", "क्रेडिट कार्ड")),
    ("electricity", ("electricity", "वीज", "power bill", "energy bill")),
    ("broadband", ("broadband", "fiber", "fibre", "wifi", "wi-fi", "internet")),
    ("mobile", ("postpaid", "prepaid", "mobile", "recharge", "मोबाईल")),
    ("insurance", ("insurance", "premium", "policy", "विमा")),
    ("loan", ("emi", "loan", "कर्ज", "हप्ता")),
    ("gas", ("gas bill", "png", "lpg", "गॅस")),
    ("water", ("water bill", "पाणी")),
    ("subscription", SUBSCRIPTION_WORDS),
]
PERIOD_WORDS = [("monthly", ("monthly", "per month", "/month", "/mo", "every month", "मासिक", "दरमहा")),
                ("quarterly", ("quarterly", "every 3 months", "त्रैमासिक")),
                ("yearly", ("yearly", "annual", "per year", "/year", "every year", "वार्षिक"))]
PERIOD_DAYS = {"monthly": 30, "quarterly": 91, "yearly": 365}


def biller_key(name: str) -> str:
    return re.sub(r"[^0-9a-zऀ-ॿ]", "", name.lower())


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


@dataclass
class BillDraft:
    biller: str
    category: str
    kind: str                       # bill | subscription | receipt
    amount_paise: int | None
    due_date: date | None
    bill_date: date
    autopay: bool = False
    period_hint: str | None = None


def _sender_name(sender: str) -> str:
    sender = (sender or "").strip()
    m = re.match(r'^\s*"?([^"<]+?)"?\s*<([^>]+)>', sender)
    if m:
        return m.group(1).strip()
    m = re.match(r"^[^@\s]+@([^@\s>]+)$", sender)
    if m:
        parts = m.group(1).split(".")
        return parts[-2].capitalize() if len(parts) >= 2 else parts[0]
    m = re.match(r"^[A-Z]{2}-([A-Z0-9]{3,})(?:-[A-Z])?$", sender)  # Indian SMS headers, e.g. VM-ABCDEF
    if m:
        return m.group(1).capitalize()
    return sender[:40]


def _pick_amount(text: str, low: str, receipt: bool) -> int | None:
    best, best_score = None, -99
    for a in find_amounts(text):
        before = low[max(0, a.start - 45):a.start]
        score = 0
        if _has(before, AMOUNT_GOOD):
            score += 2
        if "total" in before or "एकूण" in before:
            score += 1
        if "minimum" in before or "किमान" in before:
            score -= 3
        if receipt and _has(before, ("debited", "paid", "received", "payment of", "भरणा")):
            score += 1
        if score > best_score:
            best, best_score = a.paise, score
    return best


def _pick_due(text: str, low: str) -> date | None:
    for d in find_dates(text):
        before = low[max(0, d.start - 50):d.start]
        after = low[d.start:d.start + 30]
        if _has(before, DUE_BEFORE) or _has(after, DUE_AFTER):
            return d.value
    return None


def extract_bill(text: str, sender: str = "", subject: str = "", received: date | None = None,
                 billers: list[dict] | None = None, today: date | None = None) -> BillDraft | None:
    """Fields of a bill, subscription or payment receipt; None when the text is not one."""
    full = scrub(f"{subject}\n{text}")
    low = full.lower()
    head = f"{sender} {subject}".lower()
    match = None
    for b in billers or []:
        words = [str(w).lower() for w in b.get("match") or [b.get("name", "")] if w]
        if any(w and (w in head or w in low) for w in words):
            match = b
            break
    receipt = _has(low, RECEIPT_WORDS)
    autopay = _has(low, AUTOPAY_WORDS)
    subscription = _has(low, SUBSCRIPTION_WORDS) or (match or {}).get("category") == "subscription"
    billish = _has(low, BILL_WORDS)
    if not (receipt or autopay or subscription or billish):
        return None
    if re.search(r"\botp\b|one[- ]time password", low) and not billish:
        return None
    amount = _pick_amount(full, low, receipt)
    if amount is None:
        return None
    category = (match or {}).get("category") or next((c for c, words in CATEGORY_WORDS if _has(low, words)), "other")
    kind = "receipt" if receipt else ("subscription" if subscription else "bill")
    period = next((p for p, words in PERIOD_WORDS if _has(low, words)), None)
    name = (match or {}).get("name") or _sender_name(sender) or "Unknown"
    return BillDraft(biller=str(name), category=str(category), kind=kind, amount_paise=amount,
                     due_date=None if receipt else _pick_due(full, low),
                     bill_date=received or today or date.today(), autopay=autopay, period_hint=period)


# ---------------------------------------------------------------- store


@dataclass
class Bill:
    id: int
    source: str
    biller: str
    biller_key: str
    category: str
    kind: str
    amount_paise: int | None
    due_date: date | None
    bill_date: date
    status: str
    autopay: bool
    period_hint: str | None
    reminder_ids: list[int] = field(default_factory=list)

    @property
    def when(self) -> date:
        return self.due_date or self.bill_date

    def line(self) -> str:
        due = f"due {self.due_date:%d %b %Y}" if self.due_date else f"on {self.bill_date:%d %b %Y}"
        flags = (" [AutoPay]" if self.autopay else "") + (f" [{self.period_hint}]" if self.period_hint else "")
        return f"#{self.id} {self.biller} ({self.category}, {self.kind}) {format_inr(self.amount_paise)} {due} - {self.status}{flags}"


@dataclass
class Recurring:
    biller: str
    period: str
    count: int
    avg_paise: int
    last: date
    next_expected: date
    autopay: bool

    @property
    def monthly_paise(self) -> int:
        return round(self.avg_paise * 30 / PERIOD_DAYS[self.period])


_COLS = ("id, source, biller, biller_key, category, kind, amount_paise, due_date, bill_date, status, autopay, "
         "period_hint, reminder_ids")


def _bill(row) -> Bill:
    return Bill(row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                date.fromisoformat(row[7]) if row[7] else None, date.fromisoformat(row[8]), row[9], bool(row[10]),
                row[11], json.loads(row[12] or "[]"))


def text_ref(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:24]


class BillStore:
    def __init__(self, conn: sqlite3.Connection, tz: tzinfo, audit: AuditLog | None = None,
                 cfg: dict[str, Any] | None = None):
        self.db, self.tz, self.audit, self.cfg = conn, tz, audit, cfg or {}
        self.db.executescript(_SCHEMA)
        self.reminders = ReminderStore(conn, audit)

    # ---- writing ----

    def add(self, draft: BillDraft, source: str, source_ref: str, now: datetime) -> Bill | None:
        """Store a bill. None if the same message was stored before. Creates due-date reminders;
        a receipt marks a matching open bill as paid."""
        status = "paid" if draft.kind == "receipt" else "due"
        try:
            cur = self.db.execute(
                "INSERT INTO india_bills (source, source_ref, biller, biller_key, category, kind, amount_paise, due_date, "
                "bill_date, status, autopay, period_hint, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source, source_ref, draft.biller, biller_key(draft.biller), draft.category, draft.kind,
                 draft.amount_paise, draft.due_date.isoformat() if draft.due_date else None,
                 draft.bill_date.isoformat(), status, int(draft.autopay), draft.period_hint,
                 now.isoformat(timespec="seconds")))
        except sqlite3.IntegrityError:
            return None
        self.db.commit()
        bill = self.get(cur.lastrowid)  # type: ignore[arg-type]
        assert bill is not None
        if bill.status == "due":
            self._schedule(bill, now)
        else:
            self._settle(bill)
        if self.audit:
            self.audit.write("india_bill_added", bill_id=bill.id, source=source, kind=bill.kind)
        return self.get(bill.id)

    def _schedule(self, bill: Bill, now: datetime) -> None:
        if not bill.due_date:
            return
        lead = int(self.cfg.get("reminder_lead_days") or 3)
        hour = int(self.cfg.get("reminder_hour") or 9)
        text = (f"Bill due {bill.due_date:%d %b}: {bill.biller} {format_inr(bill.amount_paise)}"
                + (" (AutoPay is set; check the balance)" if bill.autopay else "") + f" [bill #{bill.id}]")
        ids = []
        for day in sorted({bill.due_date - timedelta(days=lead), bill.due_date}):
            at = datetime.combine(day, time(hour), self.tz)
            if at > now:
                ids.append(self.reminders.add(text, at, source="india_bills", now=now).id)
        self.db.execute("UPDATE india_bills SET reminder_ids=? WHERE id=?", (json.dumps(ids), bill.id))
        self.db.commit()

    def _settle(self, receipt: Bill) -> None:
        """A payment receipt closes the newest open bill of the same biller (same amount if known)."""
        for open_bill in self.list(status="due"):
            if open_bill.biller_key != receipt.biller_key:
                continue
            if receipt.amount_paise and open_bill.amount_paise and open_bill.amount_paise != receipt.amount_paise:
                continue
            self.mark_paid(open_bill.id)
            break

    def mark_paid(self, bill_id: int) -> bool:
        bill = self.get(bill_id)
        if not bill or bill.status == "paid":
            return False
        for rid in bill.reminder_ids:
            self.reminders.cancel(rid)
        self.db.execute("UPDATE india_bills SET status='paid' WHERE id=?", (bill_id,))
        self.db.commit()
        if self.audit:
            self.audit.write("india_bill_paid_marked", bill_id=bill_id)
        return True

    def ignore(self, bill_id: int) -> bool:
        bill = self.get(bill_id)
        if not bill:
            return False
        for rid in bill.reminder_ids:
            self.reminders.cancel(rid)
        self.db.execute("UPDATE india_bills SET status='ignored' WHERE id=?", (bill_id,))
        self.db.commit()
        return True

    # ---- reading ----

    def get(self, bill_id: int) -> Bill | None:
        row = self.db.execute(f"SELECT {_COLS} FROM india_bills WHERE id=?", (bill_id,)).fetchone()
        return _bill(row) if row else None

    def list(self, status: str | None = None) -> list[Bill]:
        sql = f"SELECT {_COLS} FROM india_bills" + (" WHERE status=?" if status else " WHERE status != 'ignored'")
        rows = self.db.execute(sql, (status,) if status else ()).fetchall()
        return sorted((_bill(r) for r in rows), key=lambda b: b.when)

    def due_within(self, today: date, days: int) -> list[Bill]:
        return [b for b in self.list(status="due") if b.due_date and b.due_date <= today + timedelta(days=days)]

    def recurring(self, today: date | None = None) -> list[Recurring]:
        groups: dict[str, list[Bill]] = {}
        for b in self.list():
            if b.amount_paise:
                groups.setdefault(b.biller_key, []).append(b)
        out = []
        for bills in groups.values():
            bills.sort(key=lambda b: b.when)
            # One bill and its receipt are one event: keep one entry per 10-day window.
            events: list[Bill] = []
            for b in bills:
                if events and (b.when - events[-1].when).days < 10:
                    continue
                events.append(b)
            period = None
            if len(events) >= 2:
                gap = statistics.median((b.when - a.when).days for a, b in zip(events, events[1:]))
                period = next((p for p, (lo, hi) in {"monthly": (25, 35), "quarterly": (80, 100),
                                                     "yearly": (350, 380)}.items() if lo <= gap <= hi), None)
            hints = {b.period_hint for b in bills if b.period_hint}
            if period is None and len(hints) == 1 and any(b.kind == "subscription" for b in bills):
                period = hints.pop()
            if not period:
                continue
            last = events[-1].when
            out.append(Recurring(events[-1].biller, period, len(events),
                                 round(statistics.mean(b.amount_paise for b in events)), last,  # type: ignore[misc]
                                 last + timedelta(days=PERIOD_DAYS[period]), any(b.autopay for b in bills)))
        return sorted(out, key=lambda r: r.next_expected)

    def monthly_summary(self, year: int, month: int) -> str:
        bills = [b for b in self.list() if (b.when.year, b.when.month) == (year, month) and b.amount_paise]
        title = f"Bills for {date(year, month, 1):%B %Y}"
        if not bills:
            return f"{title}: none recorded."
        by_cat: dict[str, int] = {}
        for b in bills:
            by_cat[b.category] = by_cat.get(b.category, 0) + b.amount_paise  # type: ignore[operator]
        paid = sum(b.amount_paise for b in bills if b.status == "paid")  # type: ignore[misc]
        due = sum(b.amount_paise for b in bills if b.status == "due")  # type: ignore[misc]
        lines = [f"{title}: {len(bills)} items, paid {format_inr(paid)}, still due {format_inr(due)}."]
        lines += [f"- {c}: {format_inr(v)}" for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]
        rec = self.recurring()
        if rec:
            lines.append("Recurring (about per month): " + format_inr(sum(r.monthly_paise for r in rec)))
            lines += [f"- {r.biller}: {r.period}, about {format_inr(r.avg_paise)}, next ~{r.next_expected:%d %b}"
                      + (" [AutoPay]" if r.autopay else "") for r in rec]
        return "\n".join(lines)

    # ---- payees (for UPI hand-off links; see upi.py) ----

    def add_payee(self, name: str, vpa: str, biller: str | None, now: datetime) -> int:
        from jarvis.india.upi import valid_vpa

        if not valid_vpa(vpa):
            raise ValueError("not a valid UPI ID (name@bank)")
        key = biller_key(biller or name)
        self.db.execute("INSERT OR REPLACE INTO india_payees (name, biller_key, vpa, confirmed_at) VALUES (?,?,?,?)",
                        (name.strip(), key, vpa.strip(), now.isoformat(timespec="seconds")))
        self.db.commit()
        if self.audit:
            self.audit.write("india_payee_confirmed", biller_key=key)
        return self.db.execute("SELECT id FROM india_payees WHERE biller_key=?", (key,)).fetchone()[0]

    def payees(self) -> list[dict]:
        rows = self.db.execute("SELECT id, name, biller_key, vpa, confirmed_at FROM india_payees ORDER BY name").fetchall()
        return [dict(zip(("id", "name", "biller_key", "vpa", "confirmed_at"), r)) for r in rows]

    def payee_for(self, bill: Bill) -> dict | None:
        return next((p for p in self.payees() if p["biller_key"] == bill.biller_key), None)
