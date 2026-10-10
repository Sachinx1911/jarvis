"""India tab: mutual fund NAVs, bills, the document wallet, tax deadlines and the UPI hand-off.

Everything reuses jarvis/india (stores, bill extraction, Aadhaar/PAN masking, UPI rules);
nothing here parses bill text or masks numbers on its own.

Privacy: bill and wallet details are P2. The dashboard is local (127.0.0.1 + token), so it
shows them to Sachin, but these routes never call a model and never send them to another
host. The only outbound request is AMFI's public NAV file (fixed URL from config/india.yaml),
and only when Sachin presses Refresh. Audit lines carry ids and kinds, never bill text,
amounts, names or numbers. Wallet numbers are masked by WalletStore before they are stored,
and only the masked form is ever returned.

UPI hand-off (jarvis/india/upi.py rules): a link is made only on an explicit click for one
bill, only to a payee Sachin confirmed himself (`jarvis bills payee-add`), and only after he
confirmed the payee and amount shown: like an approval, the click echoes the hash of what
was on screen. Jarvis never pays; Sachin opens the link in his own UPI app.
"""

from __future__ import annotations

import base64
import re
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.india import upi
from jarvis.india.bills import Bill, BillStore, extract_bill, text_ref
from jarvis.india.config import load_india_config, section, tz
from jarvis.india.nav import NavQuote, NavService
from jarvis.india.net import Fetcher, UrlFetcher
from jarvis.india.text import format_inr, parse_date
from jarvis.india.wallet import WalletError, WalletRecord, WalletStore
from jarvis.web.approvals import args_hash
from jarvis.web.context import WebContext
from jarvis.web.localconfig import LocalConfigError, update_local

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_SCHEMES = 30
DUE_SOON_DAYS = 7
NO_PAY = ("Jarvis does not pay. Open the link in your own UPI app (or scan the QR code, if shown), check the payee "
          "and the amount there, and enter your PIN yourself.")


class SchemeItem(BaseModel):
    code: str = Field(pattern=r"^\d{1,8}$")
    label: str = Field(default="", max_length=60)


class SchemesBody(BaseModel):
    schemes: list[SchemeItem] = Field(max_length=MAX_SCHEMES)


class RefreshBody(BaseModel):
    force: bool = True


class BillText(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    sender: str = Field(default="", max_length=200)


class UpiBody(BaseModel):
    confirm: bool = False
    args_sha256: str = Field(default="", max_length=64)


class WalletBody(BaseModel):
    doc_type: str = Field(min_length=1, max_length=40)
    holder: str = Field(min_length=1, max_length=80)
    expiry: str | None = Field(default=None, max_length=20)
    number: str = Field(default="", max_length=40)
    label: str = Field(default="", max_length=80)
    lead_days: int | None = Field(default=None, ge=0, le=365)
    file: str | None = Field(default=None, max_length=300)
    notes: str = Field(default="", max_length=500)


class ConfirmBody(BaseModel):
    confirm: bool = False


# ---- JSON views ----

def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def quote_json(q: NavQuote) -> dict[str, Any]:
    return {"code": q.code, "label": q.label, "name": q.name, "nav": q.nav, "nav_date": _iso(q.nav_date),
            "prev_nav": q.prev_nav, "prev_date": _iso(q.prev_date),
            "change": round(q.change, 4) if q.change is not None else None,
            "change_pct": round(q.change_pct, 2) if q.change_pct is not None else None}


def bill_json(b: Bill, today: date, has_payee: bool) -> dict[str, Any]:
    open_due = b.status == "due" and b.due_date is not None
    return {"id": b.id, "biller": b.biller, "category": b.category, "kind": b.kind, "source": b.source,
            "amount_paise": b.amount_paise, "amount": format_inr(b.amount_paise), "due_date": _iso(b.due_date),
            "bill_date": _iso(b.bill_date), "status": b.status, "autopay": b.autopay, "period": b.period_hint,
            "days_left": (b.due_date - today).days if open_due else None,  # type: ignore[operator]
            "overdue": open_due and b.due_date < today,  # type: ignore[operator]
            "reminders": len(b.reminder_ids), "payee": has_payee}


def record_json(r: WalletRecord, today: date) -> dict[str, Any]:
    days = (r.expiry - today).days if r.expiry else None
    return {"id": r.id, "doc_type": r.doc_type, "holder": r.holder, "label": r.label,
            "number_masked": r.number_masked, "expiry": _iso(r.expiry), "lead_days": r.lead_days,
            "file": r.file_rel, "notes": r.notes, "days_left": days, "expired": days is not None and days < 0,
            "expiring_soon": days is not None and 0 <= days <= r.lead_days, "reminders": len(r.reminder_ids)}


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    # Tests inject these through create_app(extra=...): no network, fixed time.
    def cfg() -> dict[str, Any]:
        return load_india_config(ctx.config_dir)

    def now(c: dict[str, Any]) -> datetime:
        clock = ctx.extra.get("india_clock")
        return clock() if clock else datetime.now(tz(c))

    def fetcher() -> Fetcher:
        return ctx.extra.get("india_fetcher") or UrlFetcher()

    def bills(rt, c: dict[str, Any]) -> BillStore:
        return BillStore(rt.store.conn, tz(c), rt.audit, section(c, "bills"))

    def wallet(rt, c: dict[str, Any]) -> WalletStore:
        return WalletStore(rt.store.conn, rt.paths.home, tz(c), rt.audit, section(c, "wallet"))

    def need_bill(store: BillStore, bill_id: int) -> Bill:
        b = store.get(bill_id)
        if b is None:
            raise HTTPException(404, "no such bill")
        return b

    # ---- NAVs ----

    def nav_view(rt, c: dict[str, Any], q: str = "") -> dict[str, Any]:
        svc = NavService(rt.store.conn, c, fetcher(), lambda: now(c))
        quotes = svc.search(q) if q.strip() else svc.quotes()
        last = svc.last_fetch()
        nav_cfg = section(c, "nav")
        return {"enabled": bool(nav_cfg.get("enabled", True)), "schemes": svc.schemes(), "query": q.strip(),
                "items": [quote_json(x) for x in quotes], "last_fetch": last.isoformat() if last else None,
                "fresh": svc.is_fresh(), "refresh_hours": float(nav_cfg.get("refresh_hours") or 12)}

    @r.get("/india/nav")
    def nav(q: str = "") -> dict[str, Any]:
        """Saved NAVs only (no network): the configured schemes, or a search of the saved AMFI file."""
        if len(q) > 80:
            raise HTTPException(400, "search text too long")
        c = cfg()
        with ctx.runtime() as rt:
            return nav_view(rt, c, q)

    @r.post("/india/nav/refresh")
    def nav_refresh(body: RefreshBody | None = None) -> dict[str, Any]:
        """Fetch AMFI's public NAV file now (fixed URL from config/india.yaml; nothing private is sent)."""
        c = cfg()
        with ctx.runtime() as rt:
            svc = NavService(rt.store.conn, c, fetcher(), lambda: now(c))
            error = svc.refresh(force=body.force if body else True)
            rt.audit.write("india_nav_refreshed", source="dashboard", ok=error is None)
            return {**nav_view(rt, c), "error": error}

    @r.post("/india/nav/schemes")
    def nav_schemes(body: SchemesBody) -> dict[str, Any]:
        """Replace the list of schemes in config/local.yaml (india_file: nav: schemes)."""
        schemes: list[dict[str, str]] = []
        for s in body.schemes:
            if s.code not in {x["code"] for x in schemes}:
                schemes.append({"code": s.code, "label": " ".join(s.label.split()) or s.code})
        try:
            changed = update_local(ctx.config_dir, {"india_nav_schemes": schemes})
        except LocalConfigError as e:
            raise HTTPException(409, str(e))
        ctx.audit.write("local_config_changed", source="dashboard", keys=changed)
        c = cfg()
        with ctx.runtime() as rt:
            return {"changed": changed, **nav_view(rt, c)}

    # ---- bills ----

    @r.get("/india/bills")
    def bills_list(status: Literal["due", "paid", "ignored", "all"] = "due", month: str = "") -> dict[str, Any]:
        if month and not MONTH.match(month):
            raise HTTPException(400, "month must look like 2026-10")
        c = cfg()
        today = now(c).date()
        y, m = (int(month[:4]), int(month[5:])) if month else (today.year, today.month)
        with ctx.runtime() as rt:
            store = bills(rt, c)
            items = store.list() if status == "all" else store.list(status=status)
            if month:
                items = [b for b in items if (b.when.year, b.when.month) == (y, m)]
            payees = store.payees()
            keys = {p["biller_key"] for p in payees}
            due = store.list(status="due")
            return {
                "status": status, "month": month,
                "items": [bill_json(b, today, b.biller_key in keys) for b in items],
                "counts": {"due": len(due), "due_soon": len(store.due_within(today, DUE_SOON_DAYS)),
                           "overdue": sum(1 for b in due if b.due_date and b.due_date < today)},
                "summary": store.monthly_summary(y, m),
                "recurring": [{"biller": x.biller, "period": x.period, "count": x.count,
                               "average": format_inr(x.avg_paise), "per_month": format_inr(x.monthly_paise),
                               "last": _iso(x.last), "next_expected": _iso(x.next_expected), "autopay": x.autopay}
                              for x in store.recurring(today)],
                "payees": [{"name": p["name"], "vpa": p["vpa"], "biller_key": p["biller_key"],
                            "confirmed_at": p["confirmed_at"]} for p in payees],
            }

    @r.post("/india/bills")
    def bill_add(body: BillText) -> dict[str, Any]:
        """Track a bill from a pasted SMS or email text, parsed locally by fixed rules (never a model).
        Only the extracted fields are stored, never the text."""
        c = cfg()
        n = now(c)
        draft = extract_bill(body.text, sender=body.sender, billers=section(c, "bills").get("billers") or [],
                             today=n.date())
        if draft is None:
            raise HTTPException(400, "this text does not look like a bill, subscription or payment receipt "
                                     "(no amount or bill words found)")
        with ctx.runtime() as rt:
            store = bills(rt, c)
            bill = store.add(draft, "paste", text_ref(body.text), n)
            if bill is None:
                raise HTTPException(409, "already tracked (the same text was added before)")
            return {"bill": bill_json(bill, n.date(), store.payee_for(bill) is not None)}

    def bill_mark(bill_id: int, action: Literal["paid", "ignore"]) -> dict[str, Any]:
        """Mark paid or ignored (both cancel the bill's reminders), like `jarvis bills paid|ignore`."""
        c = cfg()
        with ctx.runtime() as rt:
            store = bills(rt, c)
            b = need_bill(store, bill_id)
            if b.status == ("paid" if action == "paid" else "ignored"):
                raise HTTPException(409, f"bill #{bill_id} is already {b.status}")
            ok = store.mark_paid(bill_id) if action == "paid" else store.ignore(bill_id)
            if not ok:
                raise HTTPException(409, f"bill #{bill_id} could not be changed")
            rt.audit.write("india_bill_marked", source="dashboard", bill_id=bill_id,
                           status="paid" if action == "paid" else "ignored")
            b = need_bill(store, bill_id)
            return {"bill": bill_json(b, now(c).date(), store.payee_for(b) is not None)}

    # Two fixed paths, not /{action}: a path parameter there would also catch .../upi.
    @r.post("/india/bills/{bill_id}/paid")
    def bill_paid(bill_id: int) -> dict[str, Any]:
        return bill_mark(bill_id, "paid")

    @r.post("/india/bills/{bill_id}/ignore")
    def bill_ignore(bill_id: int) -> dict[str, Any]:
        return bill_mark(bill_id, "ignore")

    # ---- UPI hand-off: look first, then one explicit confirmed click per bill ----

    def shown(bill: Bill, payee: dict) -> dict[str, Any]:
        """What Sachin sees and confirms before the link is made."""
        return {"bill_id": bill.id, "payee": payee["name"], "vpa": payee["vpa"], "amount_paise": bill.amount_paise}

    @r.get("/india/bills/{bill_id}/upi")
    def upi_preview(bill_id: int) -> dict[str, Any]:
        """Payee and amount to check, or why no link can be made. The link itself is not returned here."""
        c = cfg()
        with ctx.runtime() as rt:
            store = bills(rt, c)
            b = need_bill(store, bill_id)
            try:
                _link, bill, payee = upi.link_for_bill(store, bill_id, explicit_request=True)
            except upi.UpiRefused as e:
                return {"bill": bill_json(b, now(c).date(), store.payee_for(b) is not None), "ready": False,
                        "reason": str(e), "payee": None, "args_sha256": ""}
            return {"bill": bill_json(bill, now(c).date(), True), "ready": True, "reason": "",
                    "payee": {"name": payee["name"], "vpa": payee["vpa"], "confirmed_at": payee["confirmed_at"]},
                    "args_sha256": args_hash(shown(bill, payee))}

    @r.post("/india/bills/{bill_id}/upi")
    def upi_link(bill_id: int, body: UpiBody) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(400, "check the payee and amount first, then confirm")
        if ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on")
        c = cfg()
        with ctx.runtime() as rt:
            store = bills(rt, c)
            need_bill(store, bill_id)
            try:
                link, bill, payee = upi.link_for_bill(store, bill_id, explicit_request=True)
            except upi.UpiRefused as e:
                raise HTTPException(409, f"no link: {e}")
            if body.args_sha256 != args_hash(shown(bill, payee)):
                raise HTTPException(409, "the payee or amount changed since you looked; check them again")
            rt.audit.write("india_upi_link_shown", source="dashboard", bill_id=bill_id)
            qr_path = upi.save_qr(link, rt.paths.home / "workspace" / "upi" / f"bill-{bill.id}.png")
            qr = ("data:image/png;base64," + base64.b64encode(qr_path.read_bytes()).decode("ascii")) if qr_path else None
            return {"bill": bill_json(bill, now(c).date(), True), "link": link, "qr": qr, "note": NO_PAY,
                    "payee": {"name": payee["name"], "vpa": payee["vpa"]}}

    # ---- document wallet ----

    def tax_view(rt, c: dict[str, Any], today: date) -> dict[str, Any]:
        tax_cfg = section(c, "tax")
        wallet(rt, c)  # makes sure the tax reminder table exists
        reminded = {row[0] for row in rt.store.conn.execute("SELECT key FROM india_tax_reminders")}
        items = []
        for item in tax_cfg.get("deadlines") or []:
            if not isinstance(item, dict) or not item.get("name") or not item.get("date"):
                continue
            raw = item["date"]
            try:
                due = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
            except ValueError:
                items.append({"name": str(item["name"]), "date": str(raw), "days_left": None, "past": False,
                              "reminders_set": False, "error": "date is not YYYY-MM-DD (config/india.yaml)"})
                continue
            items.append({"name": str(item["name"]), "date": due.isoformat(), "days_left": (due - today).days,
                          "past": due < today, "reminders_set": f"{item['name']}|{due.isoformat()}" in reminded})
        items.sort(key=lambda x: x["date"])
        return {"lead_days": int(tax_cfg.get("lead_days") or 7), "deadlines": items}

    @r.get("/india/wallet")
    def wallet_list() -> dict[str, Any]:
        c = cfg()
        today = now(c).date()
        with ctx.runtime() as rt:
            w = wallet(rt, c)
            items = [record_json(x, today) for x in w.list()]
            return {"items": items, "types": w.types,
                    "expiring_soon": sum(1 for x in items if x["expiring_soon"] or x["expired"]),
                    "default_lead_days": int(section(c, "wallet").get("default_lead_days") or 30),
                    "tax": tax_view(rt, c, today)}

    @r.post("/india/wallet")
    def wallet_add(body: WalletBody) -> dict[str, Any]:
        """Add a record. WalletStore keeps only the last 4 of the number and masks full Aadhaar/PAN
        numbers typed into any other field; the response carries only the masked form."""
        expiry = None
        if body.expiry:
            expiry = parse_date(body.expiry)
            if expiry is None:
                raise HTTPException(400, "could not read the expiry date; use YYYY-MM-DD")
        c = cfg()
        n = now(c)
        with ctx.runtime() as rt:
            try:
                rec, warnings = wallet(rt, c).add(body.doc_type, body.holder, n, expiry=expiry, number=body.number,
                                                  label=body.label, lead_days=body.lead_days, file=body.file or None,
                                                  notes=body.notes)
            except WalletError as e:
                raise HTTPException(400, f"not saved: {e}")
            return {"record": record_json(rec, n.date()), "warnings": warnings}

    @r.post("/india/wallet/{record_id}/remove")
    def wallet_remove(record_id: int, body: ConfirmBody) -> dict[str, Any]:
        """Removes the record and its reminders; a linked file is never touched."""
        if not body.confirm:
            raise HTTPException(400, "confirm the removal first")
        c = cfg()
        with ctx.runtime() as rt:
            if not wallet(rt, c).remove(record_id):
                raise HTTPException(404, "no such wallet record")
            rt.audit.write("india_wallet_record_removed", source="dashboard", record_id=record_id)
            return {"removed": record_id}

    # ---- tax deadlines (dates come from config/india.yaml, never from code) ----

    @r.post("/india/tax/reminders")
    def tax_reminders() -> dict[str, Any]:
        c = cfg()
        n = now(c)
        with ctx.runtime() as rt:
            try:
                names = wallet(rt, c).schedule_tax_reminders(section(c, "tax"), n)
            except ValueError as e:
                raise HTTPException(400, f"config/india.yaml tax.deadlines: {e}")
            rt.audit.write("india_tax_reminders_set", source="dashboard", count=len(names))
            return {"scheduled": names, "tax": tax_view(rt, c, n.date())}

    return r
