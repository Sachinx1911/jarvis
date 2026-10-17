"""Phase 9 part G: spoken addresses, teardown intents (English and Marathi), the offline drill checks,
and the front-tab reader with a fake osascript."""

from __future__ import annotations

import pytest

from jarvis.xray.drill_spoken import offline_checks
from jarvis.xray.front_tab import SCRIPT, front_tab, front_tab_url
from jarvis.xray.spoken import parse_spoken_address, teardown_intent


@pytest.mark.parametrize("said, want", [
    ("igloo dot inc", "https://igloo.inc"),
    ("stripe dot com slash pricing", "https://stripe.com/pricing"),
    ("localhost colon three thousand", "http://localhost:3000"),
    ("igloo.inc", "https://igloo.inc"),
    ("localhost कोलन ३०००", "http://localhost:3000"),
    ("localhost colon eighty eighty", "http://localhost:8080"),
    ("localhost colon eight zero eight zero", "http://localhost:8080"),
    ("localhost colon 5173 slash app", "http://localhost:5173/app"),
    ("open https://example.org/a/b now", "https://example.org/a/b"),
    ("www dot stripe dot com", "https://www.stripe.com"),
    ("Igloo Dot Inc.", "https://igloo.inc"),
    ("जार्विस igloo डॉट inc", "https://igloo.inc"),
])
def test_spoken_addresses(said, want):
    assert parse_spoken_address(said) == want


@pytest.mark.parametrize("said", ["", "   ", "hello there", "e.g. nothing", "what time is it", "192.168", "3.14 pie"])
def test_no_address_in_plain_sentences(said):
    assert parse_spoken_address(said) is None


@pytest.mark.parametrize("said, target", [
    ("reverse engineer igloo dot inc", "https://igloo.inc"),
    ("Jarvis, tear down stripe dot com slash pricing", "https://stripe.com/pricing"),
    ("teardown igloo.inc", "https://igloo.inc"),
    ("how does igloo.inc do that scroll effect", "https://igloo.inc"),
    ("what is igloo dot inc built with", "https://igloo.inc"),
    ("what's igloo.inc built with?", "https://igloo.inc"),
    ("tear down this site", "this site"),
    ("how does this page do that", "this site"),
    ("reverse engineer this site", "this site"),
    ("reverse engineer Stripe's homepage", None),
])
def test_english_intents(said, target):
    hit = teardown_intent(said)
    assert hit is not None and hit[0] == target and hit[1] == " ".join(said.split())


@pytest.mark.parametrize("said, target", [
    ("igloo.inc कसं बनवलंय", "https://igloo.inc"),
    ("igloo dot inc कसं बनवलंय?", "https://igloo.inc"),
    ("igloo dot inc चं teardown कर", "https://igloo.inc"),
    ("जार्विस, stripe dot com चं teardown कर", "https://stripe.com"),
    ("ही साइट कशी बनवली", "this site"),
    ("हे पेज कसं बनवलंय", "this site"),
    ("localhost कोलन ३००० कसं बनवलंय", "http://localhost:3000"),
])
def test_marathi_intents(said, target):
    hit = teardown_intent(said)
    assert hit is not None and hit[0] == target


@pytest.mark.parametrize("said", ["what time is it", "remember that igloo.inc is nice", "open igloo.inc",
                                  "उद्या मीटिंग आहे", "stop", ""])
def test_not_an_intent(said):
    assert teardown_intent(said) is None


def test_offline_drill_checks_pass():
    checks = offline_checks()
    assert len(checks) >= 5 and all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert sum(c.name.startswith("spoken address") for c in checks) == 5


# ---- "this site": the front tab ----

def test_front_tab_on_mac_reads_only_the_url():
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        return 0, "https://igloo.inc/\n", ""

    tab = front_tab("darwin", runner)
    assert tab.url == "https://igloo.inc/" and "osascript" in tab.reason
    assert calls == [["osascript", "-e", SCRIPT]] and "URL of active tab" in SCRIPT
    assert front_tab_url("darwin", runner) == "https://igloo.inc/"


def test_front_tab_on_mac_failures():
    assert front_tab("darwin", lambda a, t: (1, "", "Not authorized")).url is None
    assert "Automation" in front_tab("darwin", lambda a, t: (1, "", "Not authorized")).reason
    assert front_tab("darwin", lambda a, t: (0, "chrome://newtab\n", "")).url is None

    def raises(a, t):
        raise OSError("no osascript")

    assert "osascript failed" in front_tab("darwin", raises).reason


def test_front_tab_on_windows_is_not_supported_yet():
    tab = front_tab("win32", lambda a, t: (0, "https://igloo.inc", ""))
    assert tab.url is None and "not supported yet on Windows" in tab.reason
    assert front_tab_url("win32") is None
