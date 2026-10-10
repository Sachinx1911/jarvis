"""Live check (not a test): does Tavily Extract return a Rs price from Indian store pages?

Uses the Tavily key from the OS keyring (jarvis secret set tavily_api_key). Costs a few
Tavily credits. For each store it finds one laptop product page with Tavily search (or
takes URLs given on the command line), runs Tavily Extract (basic, then advanced) and
prints whether a Rs amount appears near the product name.

    .venv\\Scripts\\python.exe scripts\\check_tavily_extract.py ["url|product name" ...]
"""

from __future__ import annotations

import re
import sys

from jarvis.agents.sources import classify, find_inr_amounts, price_evidence
from jarvis.secrets import get_secret
from jarvis.tools.web import WebClient, WebError

STORES = ["croma.com", "reliancedigital.in", "vijaysales.com"]


def product_from_title(title: str) -> str:
    title = re.sub(r"^(buy)\s+", "", title.strip(), flags=re.IGNORECASE)
    title = re.split(r"\s+[-|:]\s+|\(| online", title, maxsplit=1, flags=re.IGNORECASE)[0]
    return " ".join(title.split()[:5])


def find_pages(web: WebClient, key: str) -> list[tuple[str, str]]:
    pages = []
    for store in STORES:
        try:
            results = web.tavily_search(key, f"{store} HP Dell Lenovo laptop i5 16GB 512GB SSD buy", max_results=10)
        except WebError as e:
            print(f"{store}: search failed: {e}")
            continue
        mine = [r for r in results if classify(r["url"]).kind == "store" and store in r["url"]]
        # Prefer product pages (/p/ or /product/) over category listings.
        hit = next((r for r in mine if re.search(r"/p/|/product/|/pd/", r["url"])), mine[0] if mine else None)
        if hit:
            pages.append((hit["url"], product_from_title(hit["title"])))
        else:
            print(f"{store}: no product page in search results")
    return pages


def main(argv: list[str]) -> int:
    key = get_secret("tavily_api_key")
    if not key:
        print("No Tavily key in the keyring (jarvis secret set tavily_api_key).")
        return 2
    web = WebClient()
    pages = [tuple((a.split("|", 1) + [""])[:2]) for a in argv] or find_pages(web, key)
    found = 0
    for url, product in pages:
        tier = classify(url)
        if tier.kind == "user_check":
            print(f"SKIP {url}: Amazon/Flipkart are never fetched")
            continue
        line = f"{url}\n  product guess: {product or '-'}"
        for depth in ("basic", "advanced"):
            try:
                res = web.tavily_extract(key, [url], depth=depth)
            except WebError as e:
                line += f"\n  {depth}: error {e}"
                break
            text = next((r["raw_content"] for r in res["results"] if r["raw_content"]), "")
            amounts = [a for _, a in find_inr_amounts(text)][:5]
            ev = price_evidence(text, product) if product else None
            ok = ev.ok if ev else bool(amounts)
            line += (f"\n  {depth}: {len(text)} chars, Rs amounts {amounts or 'none'}, "
                     f"near product: {ev.ok if ev else 'n/a'} {list(ev.amounts) if ev and ev.ok else ''}"
                     f"{('(' + ev.reason + ')') if ev and not ev.ok else ''}")
            if not text and res["failed_results"]:
                line += f" failed: {res['failed_results'][0]['error']}"
            if ok:
                found += 1
                break
        print(line)
    print(f"\nPrice found on {found} of {len(pages)} pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
