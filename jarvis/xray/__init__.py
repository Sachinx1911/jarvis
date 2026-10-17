"""X-ray vision (PLAN.md 18.1, Phase 9): reverse-engineer a public website's front end with REA.

- kit.py: find node and Chrome, install REA pinned at 6.5.0 (only with confirmation), run the REA CLI.
- browser.py: a fresh Chrome profile per job with a loopback debugging port, read-only CDP.
- capture.py: one ordered evidence table (REA inspect/bundle/screenshot + Jarvis assets/fingerprints).
- fingerprints.py: library/version regexes for licence banners and globals.
- teardown.py: the evidence digest becomes a note, a document and a memory (one model call).
- spoken.py, voice routes and tools.py start a job by voice, chat or the brain; cli_xray.py from the terminal.
- drill.py / drill_spoken.py: offline self-checks.

Nothing here runs node or Chrome unless a real Kit / CleanBrowser is used; tests inject fakes. Nothing is
imported at boot: a missing kit never breaks Jarvis.
"""


class XrayError(Exception):
    """A readable failure in the x-ray kit, browser or capture."""
