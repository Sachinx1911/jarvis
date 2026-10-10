"""UPI hand-off links. Jarvis NEVER pays.

Rules (CLAUDE.md: no financial transfers; reports/Personal AI capability gaps.md, payments):
1. Jarvis never initiates, approves or automates a payment, never opens a UPI app for Sachin,
   never stores a UPI PIN, and never approves a mandate.
2. A `upi://pay?...` link is built only when Sachin explicitly asks for one for a specific bill
   (CLI `jarvis bills upi <id>`, or the chat tool, which is T2 so he approves each one).
3. The payee's UPI ID comes only from a payee Sachin typed and confirmed himself
   (`jarvis bills payee-add`). A UPI ID found in an email, SMS or web page is never used, so
   a forged bill cannot redirect money.
4. The link is shown as text (and as a QR image only if the optional `qrcode` package is
   already installed). Sachin opens it in his own UPI app, which shows the payee and amount,
   and he enters his PIN there.

Link format: `upi://pay?pa=<vpa>&pn=<name>&am=<amount>&cu=INR&tn=<note>`. NPCI's own linking
specification PDF could not be fetched on 2026-10-10; the parameters (pa and pn mandatory,
am decimal, cu INR only, tn note) are from mirrored copies of "UPI Linking Specs" v1.6
and NPCI circulars that refer to them. Only these widely supported parameters are used.
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from jarvis.india.bills import Bill, BillStore

_VPA = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z][A-Za-z0-9.\-]{1,64}$")


class UpiRefused(Exception):
    pass


def valid_vpa(vpa: str) -> bool:
    return bool(_VPA.match((vpa or "").strip()))


def build_upi_link(vpa: str, name: str, amount_paise: int | None, note: str = "") -> str:
    if not valid_vpa(vpa):
        raise UpiRefused("not a valid UPI ID")
    params = [("pa", vpa.strip()), ("pn", name.strip()[:50] or "Payee")]
    if amount_paise:
        params.append(("am", f"{amount_paise / 100:.2f}"))
    params.append(("cu", "INR"))
    if note:
        params.append(("tn", re.sub(r"\s+", " ", note).strip()[:50]))
    return "upi://pay?" + "&".join(f"{k}={urllib.parse.quote(v, safe='@.-_')}" for k, v in params)


def link_for_bill(store: BillStore, bill_id: int, explicit_request: bool) -> tuple[str, Bill, dict]:
    """The hand-off link for one bill, or UpiRefused with the reason."""
    if not explicit_request:
        raise UpiRefused("a payment link is made only when Sachin explicitly asks for one")
    bill = store.get(bill_id)
    if not bill:
        raise UpiRefused(f"no bill #{bill_id}")
    if bill.status != "due":
        raise UpiRefused(f"bill #{bill_id} is {bill.status}, not due")
    payee = store.payee_for(bill)
    if not payee:
        raise UpiRefused(f"no confirmed payee for {bill.biller}. Sachin must add it himself: "
                         f"jarvis bills payee-add \"{bill.biller}\" <upi-id>")
    note = f"{bill.biller} bill" + (f" due {bill.due_date:%d %b}" if bill.due_date else "")
    return build_upi_link(payee["vpa"], payee["name"], bill.amount_paise, note), bill, payee


def save_qr(link: str, path: Path) -> Path | None:
    """PNG QR code, only if the optional `qrcode` package is installed (no new dependency)."""
    try:
        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(link).save(path)
    return path
