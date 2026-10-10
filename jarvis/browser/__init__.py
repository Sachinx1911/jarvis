"""Isolated, safe browser (PLAN.md 11.4) and browser step recording (PLAN.md section 8).

Playwright is imported only inside jarvis/browser/playwright_driver.py, and only when a
browser actually starts, so Jarvis runs (and every test passes) without it.
"""

from jarvis.browser.policy import BrowserError, DomainAllowlist, domains_from_text
from jarvis.browser.recording import browser_steps_evidence
from jarvis.browser.session import BrowserSession
from jarvis.browser.tools import browser_tools

__all__ = ["BrowserError", "BrowserSession", "DomainAllowlist", "browser_steps_evidence", "browser_tools",
           "domains_from_text"]
