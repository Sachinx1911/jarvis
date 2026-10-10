"""Verify-after-act: browser post-checks, Operator claims vs tool runs, Coder diff vs report,
and the "Claims vs evidence" receipt section. Fakes only (no model, browser or network)."""

import json
from types import SimpleNamespace

import pytest

from jarvis.browser import browser_tools
from jarvis.browser.fake import FakeDriver, FakeElement, FakePage
from jarvis.browser.session import BrowserSession, read_checks
from jarvis.config import load_config
from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolCall
from jarvis.providers.fake import FakeProvider
from jarvis.tasks.receipt import build_receipt
from jarvis.tasks.store import TaskStore
from jarvis.tasks.verify import (
    Run,
    changed_files,
    check_claims,
    check_coder,
    claim_lines,
    claimed_files,
    classify,
    folder_hashes,
)
from jarvis.tools.code import RunResult
from jarvis.tools.registry import ToolRegistry

CONFIG = {"default_allowed_domains": [], "downloads": {"max_mb": 1, "allowed_types": ["pdf"]}}


def pages():
    return {
        "https://shop.example/contact": FakePage(
            text="Contact us", title="Contact", form_action="https://shop.example/send",
            after_submit="https://shop.example/thanks",
            elements={"name": FakeElement(name="name"),
                      "Send": FakeElement(tag="button", type="submit", text="Send", submits=True),
                      "Price list": FakeElement(tag="a", text="Price list", href="https://shop.example/list.pdf",
                                                download=("list.pdf", b"%PDF-1.4 demo"))}),
        "https://shop.example/thanks": FakePage(text="Thanks! Your message was received.", title="Thanks"),
        "https://shop.example/broken": FakePage(
            text="Contact us", form_action="https://shop.example/send",
            elements={"name": FakeElement(name="name")}),
    }


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    yield tmp_path, store, audit
    store.close()


def browser_registry(env, page_map=None, after_text=None):
    home, store, audit = env
    task_dir = home / "data" / "tasks" / "t-001"
    pm = page_map or pages()
    if after_text is not None:
        pm["https://shop.example/thanks"].text = after_text
    session = BrowserSession(home, task_dir, ["shop.example"], audit=audit, config=CONFIG,
                             driver_factory=lambda: FakeDriver(pm), check_url=lambda u: None)
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit, lambda req: True))
    for t in browser_tools(session, None):
        reg.register(t)
    return reg, session, task_dir


def call(reg, name, **args):
    return reg.execute(ToolCall("c1", name, args), task_id="t-001", agent="operator")


# ---- browser post-checks ----

def test_submit_is_read_back_and_recorded_per_step(env):
    reg, session, task_dir = browser_registry(env)
    assert "[verified: page https://shop.example/contact is open]" in call(
        reg, "browser_open", url="https://shop.example/contact").content
    assert "[verified: the field holds the typed value]" in call(reg, "browser_fill", field="name",
                                                                  value="Asha Demo").content
    res = call(reg, "browser_submit")
    assert not res.is_error
    assert "[verified: page moved to https://shop.example/thanks; confirmation text 'thanks' seen; " \
           "screenshot browser/screenshots/001-after-submit.png]" in res.content
    checks = read_checks(task_dir)
    assert [c["step"] for c in checks] == ["open", "fill", "submit"] and all(c["ok"] for c in checks)
    assert checks[2]["before"] == "https://shop.example/contact" and checks[2]["title"] == "Thanks"
    # Page text never goes into the check summary, only the fixed vocabulary.
    assert "Your message" not in res.content


def test_submit_that_lands_on_an_error_is_not_verified(env):
    reg, _, task_dir = browser_registry(env, after_text="Error: name is required. Please try again.")
    call(reg, "browser_open", url="https://shop.example/contact")
    call(reg, "browser_fill", field="name", value="Asha Demo")
    res = call(reg, "browser_submit")
    assert "[NOT verified: page moved to https://shop.example/thanks; no confirmation text; error text" in res.content
    assert read_checks(task_dir)[-1]["ok"] is False


def test_submit_that_does_not_change_the_page_is_not_verified(env):
    reg, _, _ = browser_registry(env)
    call(reg, "browser_open", url="https://shop.example/broken")
    res = call(reg, "browser_submit")
    assert "[NOT verified: page did not change; no confirmation text" in res.content


def test_download_and_screenshot_are_checked_with_hash(env):
    reg, _, task_dir = browser_registry(env)
    call(reg, "browser_open", url="https://shop.example/contact")
    res = call(reg, "browser_download", link="Price list")
    assert "[verified: downloads/list.pdf exists, 13 bytes, sha256 " in res.content
    assert "[verified: browser/screenshots/001-page.png saved]" in call(reg, "browser_screenshot").content
    dl = [c for c in read_checks(task_dir) if c["step"] == "download"][0]
    assert len(dl["sha256"]) == 64


def test_fill_read_back_mismatch_is_not_verified(env):
    pm = pages()

    class Sticky(FakeDriver):
        def fill(self, target, value):  # the page ignores typing (e.g. a JS widget)
            self.actions.append(("fill", target, value))

    home, store, audit = env
    session = BrowserSession(home, home / "data" / "tasks" / "t-001", ["shop.example"], config=CONFIG,
                             driver_factory=lambda: Sticky(pm), check_url=lambda u: None)
    reg = ToolRegistry(store, audit, ApprovalGate(store, audit, lambda req: True))
    for t in browser_tools(session, None):
        reg.register(t)
    call(reg, "browser_open", url="https://shop.example/contact")
    assert "[NOT verified: the field does not hold the typed value]" in call(
        reg, "browser_fill", field="name", value="Asha Demo").content


# ---- Operator claims vs tool runs ----

def run(i, tool, args="{}", result="ok", ok=True):
    return Run(i, tool, args, result, ok, "operator")


def test_claim_parsing_uses_the_done_section():
    report = ("1. DONE:\n- Opened https://shop.example/contact\n- Filled the name field\n- Submitted the form\n"
              "2. EVIDENCE:\n- browser/screenshots/001-after-submit.png\n3. NOT DONE:\n- sent nothing else")
    assert claim_lines(report) == ["Opened https://shop.example/contact", "Filled the name field",
                                   "Submitted the form"]
    assert classify("Opened https://shop.example/contact") == ["open_page"]
    assert classify("Opened notepad") == ["open_app"]
    assert classify("The form was not sent") == ["other"]
    assert claim_lines("Opened notepad and checked it runs.") == ["Opened notepad and checked it runs."]


def test_claims_backed_by_verified_runs_pass():
    runs = [run(1, "browser_open", '{"url": "https://shop.example/contact"}', "Opened ... [verified: page open]"),
            run(2, "browser_fill", '{"field": "name"}', "Filled name. [verified: the field holds the typed value]"),
            run(3, "browser_submit", '{"page": "https://shop.example/contact"}',
                "Submitted. Receipt screenshot: browser/screenshots/001-after-submit.png.\n[verified: page moved]")]
    rep = check_claims("DONE:\n- Opened https://shop.example/contact\n- Filled the name field\n"
                       "- Submitted the contact form on shop.example", runs)
    assert rep.passed, rep.problems
    assert [c.status for c in rep.claims] == ["supported"] * 3
    assert "browser_submit run #3 (verified: page moved)" == rep.claims[2].evidence


def test_claimed_action_without_a_run_fails():
    rep = check_claims("DONE: Opened notepad and checked it runs.", [])
    assert not rep.passed and "claimed but not done: Opened notepad" in rep.problems[0]
    assert rep.claims[0].evidence == "no open_app run"


def test_unverified_or_failed_run_does_not_back_a_claim():
    runs = [run(1, "browser_submit", "{}", "Submitted.\n[NOT verified: page did not change; no confirmation text]")]
    rep = check_claims("DONE:\n- Submitted the form", runs)
    assert not rep.passed and "browser_submit run #1 failed or was not verified" in rep.problems[0]
    rep = check_claims("DONE:\n- Created notes.txt", [run(1, "write_file", '{"path": "other.txt"}', "Created other.txt")])
    assert not rep.passed  # the claim names a file no run wrote


def test_unreported_effects_are_listed_but_do_not_fail():
    runs = [run(1, "write_file", '{"path": "a.txt"}', "Created a.txt [verified: ok]"),
            run(2, "notify", '{"message": "hi"}', "Shown.")]
    rep = check_claims("DONE:\n- Created a.txt", runs)
    assert rep.passed and rep.unreported == ["notify run #2 is not mentioned in the report"]


# ---- Coder: report vs files that really changed ----

def test_coder_diff_must_match_report(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.py").write_text("y = 1\n", encoding="utf-8")
    before = folder_hashes(root, {".jarvis-history"})
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test(): pass\n", encoding="utf-8")
    (root / ".jarvis-history").mkdir()
    (root / ".jarvis-history" / "old-a.py").write_text("x = 1\n", encoding="utf-8")
    after = folder_hashes(root, {".jarvis-history"})
    assert changed_files(before, after) == {"a.py": "modified", "tests/test_a.py": "created"}
    tests_ok = [Run(1, "code_write", "{}", "Wrote a.py", True), Run(2, "run_tests", "{}", "Exit code 0 (passed) in 1s.", True)]

    good = "CHANGED:\n- a.py: fix\n- tests/test_a.py: new test\nTESTS: pytest -q passed\nOPEN: none"
    assert claimed_files(good) == {"a.py", "tests/test_a.py"}
    assert check_coder(good, before, after, tests_ok).passed

    lying = "CHANGED:\n- a.py: fix\n- b.py: new helper\n- tests/test_a.py: test"
    rep = check_coder(lying, before, after, tests_ok)
    assert not rep.passed and "the report says b.py changed, but it did not" in rep.problems

    hiding = "CHANGED:\n- a.py: fix"
    rep = check_coder(hiding, before, after, tests_ok)
    assert "tests/test_a.py was created but the report does not list it" in rep.problems


def test_coder_tests_must_pass_after_the_last_write():
    failed = [Run(1, "run_tests", "{}", "Exit code 1 (failed) in 1s.", True)]
    assert "the tests were not run, or the last test run failed" in check_coder("CHANGED: none", {}, {}, failed).problems
    late = [Run(1, "run_tests", "{}", "Exit code 0 (passed) in 1s.", True), Run(2, "code_write", "{}", "Wrote", True)]
    assert "code was changed after the last passing test run" in check_coder("CHANGED: none", {}, {}, late).problems


# ---- through the orchestrator ----

class FakeRunner:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code

    def run(self, argv, cwd, env, timeout_s, max_chars):
        return RunResult(self.exit_code, "3 passed" if self.exit_code == 0 else "1 failed", False)


PLAN = {"title": "x", "use_team": False, "research": [], "solo_instructions": "",
        "deliverable": {"filename": "done.md", "outline": "what was done"}, "acceptance_criteria": ["it is done"]}
PASS = {"passed": True, "checks": [{"criterion": "it is done", "passed": True}], "problems": []}
CFG = {"root": "workspace/code", "test_commands": ["pytest -q"], "timeout_seconds": 5, "max_output_chars": 2000}


def runner_for(isolated, mode, worker_script, exit_code=0):
    from jarvis.agents.orchestrator import TaskRunner

    store = Store(isolated / "data" / "jarvis.db")
    checker = FakeProvider(script=[{"tool": "read_file", "arguments": {"path": "done.md"}}, json.dumps(PASS)])
    providers = {"planner": FakeProvider(script=[{"json": {**PLAN, "mode": mode}}]),
                 "task_summary": FakeProvider(script=[{"json": {"summary": "Done."}}]),
                 "quarantine": FakeProvider(), "checker": checker,
                 "operator": FakeProvider(script=worker_script), "coder": FakeProvider(script=worker_script)}
    ts = TaskStore(store, isolated / "data" / "tasks")
    runner = TaskRunner(load_config(), isolated, isolated / "data" / "jarvis.db", store, ts,
                        AuditLog(isolated / "data" / "audit.jsonl"), lambda d: providers[d.route],
                        provider_override="fake", coder_config=CFG, coder_runner=FakeRunner(exit_code))
    return runner, ts, store


def receipt_of(isolated, tid):
    return (isolated / "data" / "tasks" / tid / "receipt.md").read_text(encoding="utf-8")


def test_operator_claim_without_tool_run_fails_the_task(isolated):
    runner, ts, store = runner_for(isolated, "operate", ["DONE:\n- Opened notepad and checked it runs.\nNOT DONE: none"])
    try:
        t = ts.create("Open notepad for me")
        done = runner.run(t.id)
        assert done.state == "FAILED" and "claimed but not done: Opened notepad" in done.last_error
        receipt = receipt_of(isolated, t.id)
        assert "Claims vs evidence (operator): FAIL" in receipt
        assert "- [!] Opened notepad and checked it runs. -> no open_app run" in receipt
    finally:
        store.close()


def test_operator_claim_backed_by_a_verified_write_passes(isolated):
    script = [{"tool": "write_file", "arguments": {"path": "notes.txt", "content": "shopping list"}},
              "DONE:\n- Created notes.txt with the shopping list\nEVIDENCE: notes.txt\nNOT DONE: none"]
    runner, ts, store = runner_for(isolated, "operate", script)
    try:
        t = ts.create("Make a notes file with my shopping list")
        done = runner.run(t.id)
        assert done.state == "COMPLETED", done.last_error
        receipt = receipt_of(isolated, t.id)
        assert "Claims vs evidence (operator): PASS" in receipt
        assert "- [x] Created notes.txt with the shopping list -> write_file run #1 (verified: file exists" in receipt
        assert "[x] every effect the Operator reports is backed by a successful, verified tool run" in receipt
    finally:
        store.close()


def coder_script(report, write_after=False):
    s = [{"tool": "code_write", "arguments": {"path": "hello.py", "content": "def hello():\n    return 'hi'\n"}},
         {"tool": "run_tests", "arguments": {"command": "pytest -q"}}]
    if write_after:
        s.append({"tool": "code_write", "arguments": {"path": "hello.py", "content": "def hello():\n    return 1\n"}})
    return s + [report]


def test_coder_done_only_when_tests_pass_and_report_matches(isolated):
    runner, ts, store = runner_for(isolated, "code", coder_script("CHANGED:\n- hello.py: new\nTESTS: pytest -q passed"))
    try:
        t = ts.create("Write a hello function")
        done = runner.run(t.id)
        assert done.state == "COMPLETED", done.last_error
        receipt = receipt_of(isolated, t.id)
        assert "Claims vs evidence (coder): PASS" in receipt
        assert "- [x] changed hello.py -> hello.py created (hash differs before/after)" in receipt
        assert "- [x] tests pass -> run_tests run #2 passed" in receipt
    finally:
        store.close()


@pytest.mark.parametrize("report,exit_code,write_after,why", [
    ("CHANGED:\n- hello.py\n- util.py", 0, False, "the report says util.py changed, but it did not"),
    ("CHANGED:\n- hello.py", 1, False, "the last test run failed"),
    ("CHANGED:\n- hello.py", 0, True, "code was changed after the last passing test run"),
])
def test_coder_fails_on_mismatch_failed_tests_or_late_write(isolated, report, exit_code, write_after, why):
    runner, ts, store = runner_for(isolated, "code", coder_script(report, write_after), exit_code)
    try:
        t = ts.create("Write a hello function")
        done = runner.run(t.id)
        assert done.state == "FAILED" and why in done.last_error
    finally:
        store.close()


def test_receipt_without_claims_has_no_section(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        ts = TaskStore(store, isolated / "data" / "tasks")
        t = ts.create("say hello")
        text = build_receipt(SimpleNamespace(tasks=ts, store=store), t.id)
        assert "Claims vs evidence" not in text and "Browser post-checks" not in text
    finally:
        store.close()
