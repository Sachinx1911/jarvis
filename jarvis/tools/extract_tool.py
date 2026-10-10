"""web_extract: read one page through Tavily Extract (renders JavaScript store pages), then the
quarantine. T0, taints the session.

Every result starts with a line written by Jarvis, not by the page: source tier, fetch time
and whether a Rs amount appears near the product name. The orchestrator reads that line to
decide whether a report row may call a price "confirmed".

Amazon.in and Flipkart are refused: their terms forbid automated price collection, so the
agent gives their links for the user to check instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable

from jarvis.agents.sources import PriceEvidence, classify, price_evidence, source_header
from jarvis.providers.base import ToolSpec
from jarvis.tools.registry import Tool
from jarvis.tools.web import MAX_PAGE_CHARS, WebError

if TYPE_CHECKING:
    from jarvis.tools.catalog import ToolDeps

S = {"type": "string"}

REFUSAL = ("Not fetched: {host} prices may not be collected automatically (its terms forbid it). "
           "Give this link in the report marked 'check yourself (Amazon/Flipkart link)' so the user can check "
           "the price, and use an official store page (web_extract) or an aggregator (labelled estimate) for the "
           "number: {url}")


def _focus(page: str, ev: PriceEvidence | None) -> str:
    """Keep the page within the quarantine's size, but never cut away the price evidence."""
    if len(page) <= MAX_PAGE_CHARS:
        return page
    if ev and ev.ok and ev.positions and ev.positions[0] > MAX_PAGE_CHARS - 4000:
        p = ev.positions[0]
        return page[: MAX_PAGE_CHARS - 4000] + "\n[...]\n" + page[max(0, p - 1500): p + 1500]
    return page[:MAX_PAGE_CHARS]


def make_web_extract_tool(d: "ToolDeps", now: Callable[[], datetime] = datetime.now) -> Tool:
    def web_extract(args: dict) -> str:
        url = (args.get("url") or "").strip()
        question = args.get("question") or ""
        product = (args.get("product") or "").strip()
        if not url or any(c.isspace() for c in url):
            return "Give one link without spaces."
        tier = classify(url)
        if tier.kind == "user_check":
            return REFUSAL.format(host=tier.match, url=url)
        if not d.quarantine:
            return "Reading web pages is not available."
        try:
            d.web.check_url(url)
        except WebError as e:
            return f"Could not read the page: {e}"

        page, method, notes = "", "", []
        key = d.tavily_key()
        if key:
            for depth in ("basic", "advanced"):
                try:
                    res = d.web.tavily_extract(key, [url], depth=depth)
                except WebError as e:
                    notes.append(f"Tavily: {e}")
                    break
                content = next((r["raw_content"] for r in res["results"] if r["raw_content"].strip()), "")
                if not content:
                    notes.extend(f"Tavily {depth}: {r['error'] or 'failed'}" for r in res["failed_results"][:1])
                    continue
                page, method = content, f"Tavily Extract ({depth})"
                if not product or price_evidence(page, product).ok:
                    break  # basic was enough; advanced only when the price was not found
        if not page:
            try:
                page, method = d.web.fetch_text(url), "plain fetch"
            except WebError as e:
                return "Could not read the page: " + "; ".join(notes + [str(e)])
        ev = price_evidence(page, product) if product else None
        header = source_header(url, tier, now(), method, ev)
        return header + "\n" + d.quarantine.extract(_focus(page, ev), question, url)

    return Tool(ToolSpec(
        "web_extract",
        "Read one web page (also JavaScript store pages) and answer a question from it. Use it for official store "
        "pages (Croma, Reliance Digital, Vijay Sales, brand India stores) to confirm prices and specs; give the exact "
        "product name in 'product' when you need the price. Amazon.in and Flipkart are never read: give their links "
        "for the user to check. Only use links the user gave or that came from web_search.",
        {"type": "object", "properties": {"url": S, "question": S,
                                          "product": {"type": "string",
                                                      "description": "exact product name, to check the price"}},
         "required": ["url", "question"]}),
        "T0", web_extract, taints=True)
