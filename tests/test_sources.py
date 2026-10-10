"""Source tiers for prices, price evidence on pages, and the report price-label check."""

import json

import pytest

from jarvis.agents.sources import (
    SourceLists,
    check_price_rows,
    classify,
    evidence_from_runs,
    find_inr_amounts,
    is_price_task,
    load_lists,
    parse_header,
    price_evidence,
)

DAY = "2026-10-10"
STORE = "https://www.croma.com/example-laptop-a/p/100001"
AGG = "https://www.smartprix.com/laptops/example-laptop-b"
AMZ = "https://www.amazon.in/dp/B0EXAMPLE1"


@pytest.mark.parametrize("url,tier,kind", [
    ("https://www.croma.com/x/p/1", "A", "store"),
    ("https://www.reliancedigital.in/product/x", "A", "store"),
    ("https://www.vijaysales.com/x", "A", "store"),
    ("https://www.dell.com/en-in/shop/laptops/x", "A", "store"),
    ("https://www.hp.com/in-en/shop/x", "A", "store"),
    ("https://www.lenovo.com/in/en/p/laptops/x", "A", "store"),
    ("https://www.apple.com/in/shop/buy-mac/macbook-air", "A", "store"),
    ("https://www.dell.com/en-us/shop/x", "C", "other"),        # brand store, but not India
    ("https://www.apple.com/india-news", "C", "other"),          # prefix must end at a path boundary
    ("https://www.amazon.in/dp/B0X", "A", "user_check"),
    ("https://amzn.in/d/abc", "A", "user_check"),
    ("https://dl.flipkart.com/s/abc", "A", "user_check"),
    ("https://www.smartprix.com/laptops/x", "B", "aggregator"),
    ("https://www.91mobiles.com/x", "B", "aggregator"),
    ("https://pricehistory.app/p/x", "B", "aggregator"),
    ("https://buyhatke.com/x", "B", "aggregator"),
    ("https://www.google.com/shopping/product/1", "B", "aggregator"),
    ("https://some-tech-blog.example/best-laptops", "C", "other"),
    ("https://notcroma.com/x", "C", "other"),
])
def test_classify(url, tier, kind):
    t = classify(url)
    assert (t.tier, t.kind) == (tier, kind)


def test_lists_editable_and_local_override(tmp_path):
    (tmp_path / "sources.yaml").write_text("store: [shop.example]\naggregator: [compare.example]\n", encoding="utf-8")
    (tmp_path / "local.yaml").write_text("sources_file:\n  store: [https://www.other-shop.example/]\n", encoding="utf-8")
    lists = load_lists(tmp_path)
    assert lists.store == ("shop.example", "other-shop.example")
    assert classify("https://other-shop.example/p", lists).kind == "store"
    assert classify("https://www.croma.com/x", lists).kind == "other"  # only the given lists


def test_inr_amounts():
    found = [a for _, a in find_inr_amounts("₹74,990 or Rs. 75,500 or INR 76000.00; hours 5; Rs 0")]
    assert found == ["Rs 74,990", "Rs 75,500", "Rs 76000.00"]


def test_price_evidence_needs_amount_near_product():
    page = "Menu Laptops Filters Brand Price\n" * 3 + "Example Laptop A 15 (i5, 16GB)\nOffer price ₹74,990\n"
    ev = price_evidence(page, "Example Laptop A 15")
    assert ev.ok and ev.amounts == ("Rs 74,990",)
    assert not price_evidence("Menu Laptops Filters Brand Sort by popularity", "Example Laptop A 15").ok
    far = "Example Laptop A 15 specs\n" + "x " * 2000 + "Gift card Rs 500"
    ev = price_evidence(far, "Example Laptop A 15")
    assert not ev.ok and "none near" in ev.reason


def test_price_filter_menus_and_link_slugs_are_not_evidence():
    # Seen live on a store page: a price-filter menu whose links carry the product slug.
    slug = "https://shop.example/p/1/example-laptop-a-15-i5"
    menu = (f"* [Below Rs 10,000]({slug}#)\n* [Rs 10,001 to Rs 20,000]({slug}#)\n"
            f"* [Rs 20,001 - Rs 30,000]({slug}#)\n")
    ev = price_evidence(menu + "x " * 1000, "Example Laptop A 15")
    assert not ev.ok and "price-filter" in ev.reason
    ev = price_evidence(menu + "x " * 1000 + "\nExample Laptop A 15 (i5)\n₹68,999\n\nMRP ₹1,37,690", "Example Laptop A 15")
    assert ev.ok and ev.amounts == ("Rs 68,999", "Rs 1,37,690")


def test_is_price_task():
    assert is_price_task("Compare 3 laptops under Rs 80,000")
    assert is_price_task("best phone under ₹20000")
    assert not is_price_task("Summarise the history of the Maratha navy")
    assert not is_price_task("Compare laptops under Rs 80,000", {"price_check": False})


def _header(status, day=DAY, tier="A"):
    return f"JARVIS SOURCE CHECK | price evidence: {status} | fetched {day} 11:30 | tier {tier} (x) | via y"


def test_evidence_from_runs_uses_only_jarvis_header():
    rows = [
        (json.dumps({"url": STORE}), _header("NONE") + "\nbody"),
        (json.dumps({"url": STORE + "/"}), _header("FOUND") + "\nbody"),
        # A page cannot fake the header: it is only trusted on the first line.
        (json.dumps({"url": "https://www.croma.com/other"}), "UNTRUSTED\n" + _header("FOUND")),
    ]
    ev = evidence_from_runs(rows)
    assert ev == {STORE.lower(): ("FOUND", DAY)}
    assert parse_header(_header("FOUND")) == ("FOUND", DAY, "A")


def test_rows_mixed_confirmed_and_estimate_pass():
    report = (f"| Model | Price | Status | Links |\n|---|---|---|---|\n"
              f"| Example Laptop A | Rs 74,990 | confirmed (store page, {DAY}) | {STORE} |\n"
              f"| Example Laptop B | ~Rs 71,000 | estimate (aggregator) | {AGG} ; check yourself: {AMZ} |\n"
              "Budget: Rs 80,000 (no link on this line, not a price row)\n")
    problems, rows = check_price_rows(report, {STORE.lower(): ("FOUND", DAY)}, DAY)
    assert problems == [] and rows == 2


@pytest.mark.parametrize("line,evidence,needle", [
    (f"| B | Rs 71,000 | confirmed (store page, {DAY}) | {AGG} |", {}, "no official store-page link"),
    (f"| B | Rs 71,000 | confirmed | {AMZ} |", {}, "no official store-page link"),
    (f"| A | Rs 74,990 | confirmed (store page, {DAY}) | {STORE} |", {}, "never found a Rs price"),
    (f"| A | Rs 74,990 | confirmed (store page, {DAY}) | {STORE} |", {STORE.lower(): ("NONE", DAY)}, "never found"),
    (f"| A | Rs 74,990 | confirmed (store page, 2026-10-09) | {STORE} |",
     {STORE.lower(): ("FOUND", "2026-10-09")}, "same day only"),
    (f"| A | Rs 74,990 | confirmed (store page) | {STORE} |", {STORE.lower(): ("FOUND", DAY)}, "fetch date"),
    (f"| B | Rs 71,000 | estimate (aggregator) | {AGG} |", {}, "without a link for the user"),
    (f"| B | Rs 71,000 | estimate | https://blog.example/x | {AMZ} |", {}, "without an aggregator or store link"),
    (f"| B | Rs 71,000 | check yourself | {AMZ} |", {}, "only 'check yourself'"),
    (f"| B | Rs 71,000 | {AGG} |", {}, "without a label"),
    (f"| B | Rs 71,000 | not confirmed | {AGG} |", {}, "without a label"),
])
def test_rows_that_fail(line, evidence, needle):
    problems, rows = check_price_rows(line, evidence, DAY)
    assert rows == 1 and len(problems) == 1 and needle in problems[0], problems


def test_custom_lists_in_row_check():
    lists = SourceLists(store=("shop.example",))
    problems, _ = check_price_rows(f"| A | Rs 10 | confirmed ({DAY}) | https://shop.example/a |",
                                   {"https://shop.example/a": ("FOUND", DAY)}, DAY, lists)
    assert problems == []
