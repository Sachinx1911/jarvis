"""X-ray vision (PLAN.md 18.1, Phase 9): observe a public web page with REA and a clean Chrome.

- kit.py: find node and Chrome, install REA pinned at 6.5.0 (only with confirmation), run the REA CLI.
- browser.py: a fresh Chrome profile per job with a loopback debugging port, read-only CDP.
- capture.py: one ordered evidence table (REA inspect/bundle/screenshot + Jarvis assets/fingerprints).
- fingerprints.py: library/version regexes for licence banners and globals.
- drill.py: offline self-checks.

Nothing here runs node or Chrome unless a real Kit / CleanBrowser is used; tests inject fakes.
"""


class XrayError(Exception):
    """A readable failure in the x-ray kit, browser or capture."""
