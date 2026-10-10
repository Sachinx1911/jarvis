"""Bills tracker: extraction (English + Marathi, email + SMS), recurring detection, reminders,
receipts settling bills, Gmail import (bodies parsed locally), UPI hand-off rules.

Every message here is synthetic: example billers, example addresses, made-up amounts.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from jarvis.connectors.google.fake import FakeGoogleClient
from jarvis.db import Store
from jarvis.india.bills import BillDraft, BillStore, extract_bill, text_ref
from jarvis.india.gmail_import import import_from_gmail
from jarvis.india.text import find_amounts, find_dates, format_inr
from jarvis.india.upi import UpiRefused, build_upi_link, link_for_bill, valid_vpa
from jarvis.proactive.reminders import ReminderStore

IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
NOW = datetime(2026, 10, 10, 8, 0, tzinfo=IST)
TODAY = NOW.date()
BILLERS = [
    {"name": "MSEDCL", "match": ["msedcl", "mahavitaran", "महावितरण"], "category": "electricity"},
    {"name": "Airtel", "match": ["airtel"], "category": "mobile"},
    {"name": "Netflix", "match": ["netflix"], "category": "subscription"},
    {"name": "LIC", "match": ["lic of india"], "category": "insurance"},
]
CFG = {"reminder_lead_days": 3, "reminder_hour": 9, "billers": BILLERS, "gmail_query": "newer_than:60d"}

EMAIL_MSEDCL = ("Dear Consumer, Consumer No 170012345678. Bill amount Rs. 1,234.50 for September 2026. "
                "Due date: 20-10-2026. Pay before due date to avoid late fee.")
EMAIL_CARD = ("Your Example Bank Credit Card statement is ready. Minimum Amount Due: ₹625.00. "
              "Total Amount Due: ₹12,500.00. Payment Due Date: 05 Nov 2026.")
SMS_MR_MSEDCL = "महावितरण: आपले वीज बिल रु. ८४०.०० आहे. देय तारीख १५/१०/२०२६. कृपया वेळेत भरणा करा."
SMS_MR_MOBILE = "आपल्या मोबाईल बिलाची रक्कम ₹४९९ असून २५ ऑक्टोबर २०२६ पर्यंत भरावी."
EMAIL_NETFLIX = "Your Netflix membership renews on 12 Nov 2026. ₹649/month will be charged via AutoPay (e-mandate)."
RECEIPT_MSEDCL = "Payment received: Rs 1,234.50 towards your MSEDCL bill. Thank you for your payment."


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "j.db")
    yield BillStore(s.conn, IST, cfg=CFG)
    s.close()


# ---------------------------------------------------------------- text helpers


def test_amounts_dates_and_indian_grouping():
    assert [a.paise for a in find_amounts("Rs. 1,23,456.5 and ₹ 99 and 250/- and INR 10")] == [12345650, 9900, 25000, 1000]
    assert [a.paise for a in find_amounts("रु. ८४०.०० आणि ४९९ रुपये")] == [84000, 49900]
    assert [d.value for d in find_dates("on 05 Nov 2026, 2026-12-01, 15/10/26, Nov 3, 2026, १ जानेवारी २०२७")] == [
        date(2026, 11, 5), date(2026, 12, 1), date(2026, 10, 15), date(2026, 11, 3), date(2027, 1, 1)]
    assert format_inr(12345650) == "Rs 1,23,456.50" and format_inr(99900) == "Rs 999"


# ---------------------------------------------------------------- extraction


def test_english_electricity_email():
    d = extract_bill(EMAIL_MSEDCL, sender="MSEDCL Billing <bills@example.com>",
                     subject="Your electricity bill", received=TODAY, billers=BILLERS)
    assert (d.biller, d.category, d.kind, d.amount_paise, d.due_date) == (
        "MSEDCL", "electricity", "bill", 123450, date(2026, 10, 20))


def test_credit_card_prefers_total_over_minimum():
    d = extract_bill(EMAIL_CARD, sender="Example Bank <cards@bank.example>", subject="Credit card statement",
                     received=TODAY, billers=BILLERS)
    assert (d.category, d.amount_paise, d.due_date) == ("credit_card", 1250000, date(2026, 11, 5))
    assert d.biller == "Example Bank"


def test_marathi_sms_with_devanagari_digits():
    d = extract_bill(SMS_MR_MSEDCL, sender="VM-MAHAVT", received=TODAY, billers=BILLERS)
    assert (d.biller, d.category, d.amount_paise, d.due_date) == ("MSEDCL", "electricity", 84000, date(2026, 10, 15))


def test_marathi_month_name_and_paryant():
    d = extract_bill(SMS_MR_MOBILE, sender="VM-AIRTEL", received=TODAY, billers=BILLERS)
    assert (d.biller, d.category, d.amount_paise, d.due_date) == ("Airtel", "mobile", 49900, date(2026, 10, 25))


def test_subscription_with_autopay_and_period():
    d = extract_bill(EMAIL_NETFLIX, sender="Netflix <info@mailer.example>", subject="Membership renewal",
                     received=TODAY, billers=BILLERS)
    assert (d.kind, d.autopay, d.period_hint, d.amount_paise, d.due_date) == (
        "subscription", True, "monthly", 64900, date(2026, 11, 12))


def test_receipt_and_non_bills():
    r = extract_bill(RECEIPT_MSEDCL, sender="MSEDCL <noreply@example.com>", received=TODAY, billers=BILLERS)
    assert r.kind == "receipt" and r.due_date is None and r.amount_paise == 123450
    assert extract_bill("Your OTP is 482913 for a transaction of Rs 500.", sender="VM-BANKX") is None
    assert extract_bill("Lunch tomorrow at 1? Bring the bill book.") is None   # bill word, no amount
    assert extract_bill("See you at 5.") is None


def test_unknown_sender_falls_back_to_display_name_or_sms_header():
    d = extract_bill("Invoice total Rs 300, due date 01-11-2026", sender="Example Water Works <a@water.example>")
    assert d.biller == "Example Water Works"
    d = extract_bill("Bill amount Rs 300, due date 01-11-2026", sender="AD-CITYGS")
    assert d.biller == "Citygs"


# ---------------------------------------------------------------- store, reminders, receipts


def test_due_bill_creates_reminders_and_receipt_settles_it(store):
    d = extract_bill(EMAIL_MSEDCL, sender="MSEDCL <b@example.com>", received=TODAY, billers=BILLERS)
    bill = store.add(d, "gmail", "m1", NOW)
    assert bill.status == "due" and len(bill.reminder_ids) == 2
    rem = ReminderStore(store.db)
    due_times = sorted(r.due_at for r in rem.pending())
    assert due_times == [datetime(2026, 10, 17, 9, 0, tzinfo=IST), datetime(2026, 10, 20, 9, 0, tzinfo=IST)]
    assert "MSEDCL Rs 1,234.50" in rem.pending()[0].text

    assert store.add(d, "gmail", "m1", NOW) is None          # same message twice: stored once

    receipt = extract_bill(RECEIPT_MSEDCL, sender="MSEDCL <b@example.com>", received=TODAY, billers=BILLERS)
    store.add(receipt, "gmail", "m2", NOW)
    assert store.get(bill.id).status == "paid"
    assert rem.pending() == []                                # reminders cancelled


def test_past_reminder_times_are_skipped(store):
    d = BillDraft("Airtel", "mobile", "bill", 49900, date(2026, 10, 11), TODAY)
    bill = store.add(d, "paste", "x", NOW)
    assert len(bill.reminder_ids) == 1                        # lead day (8 Oct) already passed


def test_recurring_detection_and_monthly_summary(store):
    for i, day in enumerate([date(2026, 8, 12), date(2026, 9, 12), date(2026, 10, 12)]):
        store.add(BillDraft("Netflix", "subscription", "subscription", 64900, day, day, autopay=True), "gmail",
                  f"n{i}", NOW)
    store.add(BillDraft("Example Insurance", "insurance", "bill", 500000, date(2026, 10, 20), TODAY), "paste", "i1", NOW)
    rec = store.recurring()
    assert len(rec) == 1
    r = rec[0]
    assert (r.biller, r.period, r.count, r.avg_paise, r.autopay) == ("Netflix", "monthly", 3, 64900, True)
    assert r.next_expected == date(2026, 11, 11)
    summary = store.monthly_summary(2026, 10)
    assert "2 items" in summary and "insurance: Rs 5,000" in summary and "Netflix: monthly" in summary


def test_single_subscription_with_period_hint_counts_as_recurring(store):
    d = extract_bill(EMAIL_NETFLIX, sender="Netflix <i@x.example>", received=TODAY, billers=BILLERS)
    store.add(d, "gmail", "n", NOW)
    assert [(r.biller, r.period) for r in store.recurring()] == [("Netflix", "monthly")]


def test_mark_paid_and_ignore(store):
    bill = store.add(BillDraft("Airtel", "mobile", "bill", 49900, date(2026, 10, 25), TODAY), "paste", "a", NOW)
    assert store.mark_paid(bill.id) and not store.mark_paid(bill.id)
    other = store.add(BillDraft("Airtel", "mobile", "bill", 100, date(2026, 11, 25), TODAY), "paste", "b", NOW)
    assert store.ignore(other.id)
    assert [b.id for b in store.list()] == [bill.id]


def test_text_ref_ignores_whitespace():
    assert text_ref("a  b\nc") == text_ref("a b c")


# ---------------------------------------------------------------- Gmail import


def test_gmail_import_parses_bodies_locally(store):
    msgs = [
        {"id": "g1", "threadId": "t", "from": "MSEDCL <b@example.com>", "to": "me", "subject": "Electricity bill",
         "date": "Fri, 09 Oct 2026 10:00:00 +0530", "snippet": "", "body": EMAIL_MSEDCL, "labelIds": []},
        {"id": "g2", "threadId": "t", "from": "Friend <f@example.com>", "to": "me", "subject": "Hi",
         "date": "Fri, 09 Oct 2026 11:00:00 +0530", "snippet": "", "body": "Dinner on Sunday?", "labelIds": []},
    ]
    client = FakeGoogleClient(messages=msgs)
    report = import_from_gmail(store, client, CFG, NOW)
    assert (report.seen, report.added, report.not_bills, report.error) == (2, 1, 1, None)
    assert store.get(report.bill_ids[0]).bill_date == date(2026, 10, 9)
    again = import_from_gmail(store, client, CFG, NOW)
    assert again.added == 0 and again.duplicates == 1
    # Only extracted fields are stored, never the body text.
    dump = "\n".join(store.db.iterdump())
    assert "Pay before due date" not in dump and "170012345678" not in dump


def test_gmail_not_connected_and_failure(store):
    assert "not connected" in import_from_gmail(store, None, CFG, NOW).error
    assert "Gmail:" in import_from_gmail(store, FakeGoogleClient(fail=True), CFG, NOW).error


def test_secrets_in_bill_text_are_never_stored(store):
    text = ("LIC of India premium due Rs 5,000 on 01-12-2026 for policy holder with Aadhaar 2345 6789 0123 "
            "and PAN ABCDE1234F. Your OTP is 556677.")
    d = extract_bill(text, sender="LIC of India <x@example.com>", received=TODAY, billers=BILLERS)
    store.add(d, "paste", text_ref(text), NOW)
    dump = "\n".join(store.db.iterdump())
    for secret in ("2345 6789 0123", "ABCDE1234F", "556677"):
        assert secret not in dump


# ---------------------------------------------------------------- UPI hand-off


def test_upi_link_rules(store):
    bill = store.add(BillDraft("MSEDCL", "electricity", "bill", 123450, date(2026, 10, 20), TODAY), "paste", "u", NOW)
    with pytest.raises(UpiRefused, match="explicitly"):
        link_for_bill(store, bill.id, explicit_request=False)
    with pytest.raises(UpiRefused, match="no confirmed payee"):
        link_for_bill(store, bill.id, explicit_request=True)
    store.add_payee("MSEDCL Payments", "msedcl.example@okbank", "MSEDCL", NOW)
    link, _, payee = link_for_bill(store, bill.id, explicit_request=True)
    assert link == ("upi://pay?pa=msedcl.example@okbank&pn=MSEDCL%20Payments&am=1234.50&cu=INR"
                    "&tn=MSEDCL%20bill%20due%2020%20Oct")
    store.mark_paid(bill.id)
    with pytest.raises(UpiRefused, match="paid"):
        link_for_bill(store, bill.id, explicit_request=True)


def test_upi_id_in_a_message_never_becomes_a_payee(store):
    text = "Electricity bill Rs 999 due date 25-10-2026. Pay now to UPI ID attacker@okfake for faster service."
    d = extract_bill(text, sender="MSEDCL <spoof@example.net>", received=TODAY, billers=BILLERS)
    bill = store.add(d, "gmail", "spoof", NOW)
    assert store.payees() == []
    with pytest.raises(UpiRefused):
        link_for_bill(store, bill.id, explicit_request=True)


def test_vpa_validation_and_encoding(store):
    assert valid_vpa("name.surname@okbank") and not valid_vpa("no-at-sign") and not valid_vpa("a@b@c")
    with pytest.raises(UpiRefused):
        build_upi_link("bad", "x", 100)
    with pytest.raises(ValueError):
        store.add_payee("X", "not a upi id", None, NOW)
    link = build_upi_link("shop@okbank", "A & B Stores", None, "note&x=1")
    assert "am=" not in link and "pn=A%20%26%20B%20Stores" in link and "tn=note%26x%3D1" in link
