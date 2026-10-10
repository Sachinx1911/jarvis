"""CLI for the India features: jarvis nav | bills ... | wallet ... | imd ...

The lead adds this module to build_parser_with_extensions() in cli.py (register() returns
{name: handler}, handler(args, out, inp, approver_factory) -> int, like cli_tasks).
"""

from __future__ import annotations

import argparse
import getpass
from datetime import date, datetime
from typing import Callable, TextIO

from jarvis.india.config import load_india_config, section, tz
from jarvis.india.net import Fetcher, UrlFetcher

# Replaceable in tests (no network, fixed time).
CLOCK: Callable[[], datetime] | None = None
FETCHER: Fetcher | None = None
GOOGLE_CLIENT_FACTORY: Callable[[], object] | None = None
IMD_SECRETS = ("imd_api_key", "imd_jwt")


def register(sub) -> dict[str, Callable]:
    nav = sub.add_parser("nav", help="mutual fund NAVs from AMFI (your schemes, or search)")
    nav.add_argument("query", nargs="*", help="scheme code or name words; empty = your schemes")
    nav.add_argument("--refresh", action="store_true", help="fetch AMFI's file now")

    bills = sub.add_parser("bills", help="bills, subscriptions and AutoPay tracker (never pays)")
    bills.add_argument("action", choices=["list", "add", "import-gmail", "paid", "ignore", "summary", "recurring",
                                          "upi", "payee-add", "payees"])
    bills.add_argument("text", nargs="*", help="bill text, a bill id, or payee name and UPI ID")
    bills.add_argument("--status", choices=["due", "paid", "all"], default="all")
    bills.add_argument("--month", help="YYYY-MM (summary, list)")
    bills.add_argument("--sender", default="", help="add: who sent the SMS/email")
    bills.add_argument("--biller", help="payee-add: the biller this payee is for (default: the payee name)")

    wallet = sub.add_parser("wallet", help="local document wallet (numbers masked) and tax-deadline reminders")
    wallet.add_argument("action", choices=["list", "add", "remove", "tax-reminders"])
    wallet.add_argument("id", nargs="?", type=int)
    wallet.add_argument("--type", dest="doc_type")
    wallet.add_argument("--holder")
    wallet.add_argument("--expiry", help="YYYY-MM-DD")
    wallet.add_argument("--number", default="", help="only the last 4 characters are kept; typing just those is enough")
    wallet.add_argument("--label", default="")
    wallet.add_argument("--lead-days", type=int)
    wallet.add_argument("--file", help="path inside the workspace folder (you add the file yourself)")
    wallet.add_argument("--notes", default="")

    imd = sub.add_parser("imd", help="IMD API key and token (stored in the OS secret store)")
    imd.add_argument("action", choices=["set-key", "set-token", "status"])
    return {"nav": cmd_nav, "bills": cmd_bills, "wallet": cmd_wallet, "imd": cmd_imd}


def _now(cfg: dict) -> datetime:
    return CLOCK() if CLOCK else datetime.now(tz(cfg))


def _fetcher() -> Fetcher:
    return FETCHER or UrlFetcher()


def cmd_nav(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.core.runtime import open_runtime
    from jarvis.india.nav import NavService, format_quotes

    cfg = load_india_config()
    rt = open_runtime()
    try:
        svc = NavService(rt.store.conn, cfg, _fetcher(), lambda: _now(cfg))
        error = svc.refresh(force=args.refresh)
        if error:
            print(f"{error} (showing saved NAVs)", file=out)
        query = " ".join(args.query)
        quotes = svc.search(query) if query else svc.quotes()
        if not quotes:
            print("No schemes set. Add them in config/local.yaml under india_file: nav: schemes."
                  if not query else f"No scheme matches {query!r}.", file=out)
            return 0 if not query else 1
        print(format_quotes(quotes), file=out)
        return 0
    finally:
        rt.close()


def _read_text(args: argparse.Namespace, inp: TextIO, out: TextIO) -> str:
    if args.text:
        return " ".join(args.text)
    print("Paste the SMS or email text, then an empty line:", file=out)
    lines = []
    for line in iter(inp.readline, ""):
        if not line.strip():
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def _id(args: argparse.Namespace) -> int | None:
    try:
        return int(args.text[0])
    except (IndexError, ValueError):
        return None


def cmd_bills(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.core.runtime import open_runtime
    from jarvis.india.bills import BillStore, extract_bill, text_ref

    cfg = load_india_config()
    bcfg = section(cfg, "bills")
    now = _now(cfg)
    rt = open_runtime()
    try:
        store = BillStore(rt.store.conn, tz(cfg), rt.audit, bcfg)
        a = args.action
        if a == "list":
            bills = store.list() if args.status == "all" else store.list(status=args.status)
            if args.month:
                y, m = (int(x) for x in args.month.split("-")[:2])
                bills = [b for b in bills if (b.when.year, b.when.month) == (y, m)]
            for b in bills:
                print(b.line(), file=out)
            if not bills:
                print("No bills tracked yet. Add one: jarvis bills add (paste the SMS), or jarvis bills import-gmail.",
                      file=out)
            return 0
        if a == "add":
            text = _read_text(args, inp, out)
            draft = extract_bill(text, sender=args.sender, billers=bcfg.get("billers") or [], today=now.date())
            if draft is None:
                print("Not a bill, subscription or receipt (no amount or bill words found).", file=out)
                return 1
            bill = store.add(draft, "paste", text_ref(text), now)
            if bill is None:
                print("Already tracked.", file=out)
                return 0
            print(f"Tracked: {bill.line()}" + (f" ({len(bill.reminder_ids)} reminder(s) set)" if bill.reminder_ids
                                                else ""), file=out)
            return 0
        if a == "import-gmail":
            from jarvis.india.gmail_import import default_client_factory, import_from_gmail

            factory = GOOGLE_CLIENT_FACTORY or default_client_factory()
            report = import_from_gmail(store, factory(), bcfg, now)
            print(report.text(), file=out)
            for bid in report.bill_ids:
                print(f"  {store.get(bid).line()}", file=out)  # type: ignore[union-attr]
            return 1 if report.error else 0
        if a in ("paid", "ignore"):
            bid = _id(args)
            ok = bid is not None and (store.mark_paid(bid) if a == "paid" else store.ignore(bid))
            print(f"Bill #{bid} marked {'paid' if a == 'paid' else 'ignored'}." if ok
                  else "Give the id of a tracked bill (see: jarvis bills list).", file=out)
            return 0 if ok else 1
        if a == "summary":
            y, m = (int(x) for x in (args.month or f"{now:%Y-%m}").split("-")[:2])
            print(store.monthly_summary(y, m), file=out)
            return 0
        if a == "recurring":
            rec = store.recurring()
            for r in rec:
                print(f"{r.biller}: {r.period}, {r.count} seen, about {r.avg_paise / 100:,.2f}, last {r.last:%d %b %Y}, "
                      f"next ~{r.next_expected:%d %b %Y}" + (" [AutoPay]" if r.autopay else ""), file=out)
            if not rec:
                print("No recurring bills found yet (needs two or more of the same biller).", file=out)
            return 0
        if a == "payees":
            for p in store.payees():
                print(f"{p['name']} -> {p['vpa']} (for {p['biller_key']}, confirmed {p['confirmed_at']})", file=out)
            if not store.payees():
                print("No payees. Add one you trust: jarvis bills payee-add \"<name>\" <upi-id>", file=out)
            return 0
        if a == "payee-add":
            if len(args.text) < 2:
                print("Usage: jarvis bills payee-add \"<name>\" <upi-id> [--biller <biller>]", file=out)
                return 1
            name, vpa = " ".join(args.text[:-1]), args.text[-1]
            out.write(f"Payee {name!r}, UPI ID {vpa}, for biller {args.biller or name!r}.\n"
                      "Did you take this UPI ID from the biller's official app, website or bill yourself? [y/N] ")
            out.flush()
            if inp.readline().strip().lower() not in ("y", "yes", "ho", "हो"):
                print("Not saved.", file=out)
                return 1
            try:
                store.add_payee(name, vpa, args.biller, now)
            except ValueError as e:
                print(f"Not saved: {e}.", file=out)
                return 1
            print("Payee saved.", file=out)
            return 0
        if a == "upi":
            from jarvis.india.upi import UpiRefused, link_for_bill, save_qr

            bid = _id(args)
            if bid is None:
                print("Give the bill id: jarvis bills upi <id>", file=out)
                return 1
            try:
                link, bill, payee = link_for_bill(store, bid, explicit_request=True)
            except UpiRefused as e:
                print(f"No link: {e}.", file=out)
                return 1
            rt.audit.write("india_upi_link_shown", bill_id=bid)
            print(f"Bill #{bill.id}: {bill.biller}, payee {payee['name']} ({payee['vpa']})", file=out)
            print(link, file=out)
            qr = save_qr(link, rt.paths.home / "workspace" / "upi" / f"bill-{bill.id}.png")
            if qr:
                print(f"QR code: {qr}", file=out)
            print("Jarvis does not pay. Open the link in your own UPI app, check payee and amount, enter your PIN there.",
                  file=out)
            return 0
        return 1
    finally:
        rt.close()


def cmd_wallet(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.core.runtime import open_runtime
    from jarvis.india.text import parse_date
    from jarvis.india.wallet import WalletError, WalletStore

    cfg = load_india_config()
    now = _now(cfg)
    rt = open_runtime()
    try:
        wallet = WalletStore(rt.store.conn, rt.paths.home, tz(cfg), rt.audit, section(cfg, "wallet"))
        if args.action == "list":
            records = wallet.list()
            for r in records:
                print(r.line(), file=out)
            if not records:
                print("The wallet is empty. Add: jarvis wallet add --type passport --holder <name> --expiry YYYY-MM-DD",
                      file=out)
            return 0
        if args.action == "add":
            if not args.doc_type or not args.holder:
                print(f"Need --type ({', '.join(wallet.types)}) and --holder.", file=out)
                return 1
            expiry: date | None = parse_date(args.expiry) if args.expiry else None
            if args.expiry and expiry is None:
                print("Could not read --expiry; use YYYY-MM-DD.", file=out)
                return 1
            try:
                rec, warnings = wallet.add(args.doc_type, args.holder, now, expiry=expiry, number=args.number,
                                           label=args.label, lead_days=args.lead_days, file=args.file, notes=args.notes)
            except WalletError as e:
                print(f"Not saved: {e}.", file=out)
                return 1
            print(f"Saved: {rec.line()}", file=out)
            for w in warnings:
                print(f"  note: {w}", file=out)
            if rec.reminder_ids:
                print(f"  {len(rec.reminder_ids)} expiry reminder(s) set.", file=out)
            return 0
        if args.action == "remove":
            ok = args.id is not None and wallet.remove(args.id)
            print(f"Removed record #{args.id} (the file itself is kept)." if ok else "Give a record id (jarvis wallet list).",
                  file=out)
            return 0 if ok else 1
        names = wallet.schedule_tax_reminders(section(cfg, "tax"), now)
        print("Tax reminders set: " + ", ".join(names) if names else "No new tax deadlines to remind (config/india.yaml: "
              "tax.deadlines).", file=out)
        return 0
    finally:
        rt.close()


def cmd_imd(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.secrets import get_secret, set_secret

    if args.action == "status":
        for name in IMD_SECRETS:
            print(f"{name}: {'set' if get_secret(name) else 'not set'}", file=out)
        return 0
    name = "imd_api_key" if args.action == "set-key" else "imd_jwt"
    value = getpass.getpass(f"Paste {name} from IMD (input hidden): ").strip()
    if not value:
        print("Nothing entered; unchanged.", file=out)
        return 1
    set_secret(name, value)
    print(f"{name} saved in the OS secret store.", file=out)
    return 0
