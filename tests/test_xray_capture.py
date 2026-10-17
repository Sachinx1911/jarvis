"""Phase 9 part F: one capture with recorded REA JSON, a fake browser and a fake runner.
No network, node or Chrome; every address is made up."""

import json
from pathlib import Path

import pytest

from jarvis.control.audit import AuditLog
from jarvis.tools.web import WebError
from jarvis.xray import XrayError
from jarvis.xray.capture import (
    ASSETS_JS,
    GLOBALS_JS,
    HTML_JS,
    JARVIS,
    REA,
    Capture,
    assets_from_entries,
    capture,
    check_capture_url,
    flatten,
)
from jarvis.xray.drill import offline_checks
from jarvis.xray.fingerprints import find_in_text, from_globals
from jarvis.xray.kit import Kit, RunResult
from tests.test_xray_kit import FakeRunner, write_installed

FIXTURES = Path(__file__).parent / "fixtures" / "xray"
HELP = {
    "inspect-web-page": "Usage: rea inspect-web-page\n  --url <url>\n  --port <n>\n  --observation-ms <ms>\n"
                        "  --include-script-sources\n  --json\n",
    "analyze-web-bundle": "Usage: rea analyze-web-bundle\n  --url <url>\n  --port <n>\n  --json\n",
    "capture-web-screenshot": "Usage: rea capture-web-screenshot\n  --url <url>\n  --port <n>\n  --output <file>\n  --json\n",
}
ENTRIES = [
    {"name": "https://demo-site.test/assets/three.module.js", "type": "script", "bytes": 612400},
    {"name": "https://demo-site.test/assets/app.js", "type": "script", "bytes": 48210},
    {"name": "https://demo-site.test/assets/hero.webp", "type": "img", "bytes": 230000},
    {"name": "https://demo-site.test/assets/model.glb", "type": "fetch", "bytes": 1_800_000},
    {"name": "https://demo-site.test/assets/site.css", "type": "link", "bytes": 12000},
    {"name": "https://demo-site.test/assets/Inter.woff2", "type": "css", "bytes": 90000},
    {"name": "https://demo-site.test/api/config", "type": "fetch", "bytes": 800},
] + [{"name": f"https://demo-site.test/assets/img{i}.png", "type": "img", "bytes": 1000 + i} for i in range(10)]
GLOBALS = {"THREE.REVISION": "165", "gsap.version": "3.12.5", "Lenis": "present", "webpackChunk": None,
           "React.version": None}
HTML = "<html><head><script src='/assets/three.module.js'></script><script src='/assets/gsap.min.js'></script>" \
       "<script src='/assets/swiper-bundle.min.js'></script></head><body>Demo</body></html>"


def public_ok(url):
    if "192.168." in url or "10.0." in url:
        raise WebError("local and private network addresses are blocked")


class ReaRunner(FakeRunner):
    """Answers REA commands from the fixtures; records what ran."""

    def __init__(self, tmp_path, fail=None, help_text=None):
        super().__init__()
        self.tmp_path = tmp_path
        self.fail = fail or set()
        self.help_text = help_text if help_text is not None else HELP

    def __call__(self, argv, timeout, cwd):
        self.calls.append((list(argv), timeout, cwd))
        if "--help" in argv:
            return RunResult(0, self.help_text.get(argv[-2], ""), "")
        cmd = argv[2] if len(argv) > 2 else ""
        if cmd in self.fail:
            return RunResult(1, "", f"Error: {cmd} failed in the fake\n  at main")
        if cmd == "inspect-web-page":
            return RunResult(0, (FIXTURES / "inspect.json").read_text(encoding="utf-8"), "")
        if cmd == "analyze-web-bundle":
            return RunResult(0, (FIXTURES / "bundle.json").read_text(encoding="utf-8"), "")
        if cmd == "capture-web-screenshot":
            out = Path(argv[argv.index("--output") + 1]) if "--output" in argv else self.tmp_path / "shot.png"
            out.write_bytes(b"\x89PNG fake")
            return RunResult(0, json.dumps({"path": str(out), "width": 1280, "height": 820}), "")
        return RunResult(0, "{}", "")


class FakeBrowser:
    def __init__(self, answers=None, fail_open=False):
        self.port = 9444
        self.headless = True
        self.answers = answers if answers is not None else {
            ASSETS_JS: json.dumps(ENTRIES), GLOBALS_JS: json.dumps(GLOBALS), HTML_JS: HTML}
        self.fail_open = fail_open
        self.entered = self.exited = False
        self.opened: list[str] = []
        self.scrolls: list[int] = []
        self.to_top = 0
        self.evaluated: list[str] = []

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True

    def open(self, url):
        if self.fail_open:
            raise XrayError("Chrome refused to open a tab (HTTP 500)")
        self.opened.append(url)
        return "complete"

    def scroll(self, steps=16):
        self.scrolls.append(steps)
        return steps

    def scroll_to_top(self):
        self.to_top += 1

    def evaluate(self, expr):
        self.evaluated.append(expr)
        return self.answers.get(expr)


def make_kit(tmp_path, runner):
    write_installed(tmp_path / "rea")
    return Kit(root=tmp_path / "rea", runner=runner, platform="linux", which=lambda n: "node" if n == "node" else None)


def events(tmp_path):
    return [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- egress ----

def test_private_and_local_addresses_are_refused(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    kit = make_kit(tmp_path, ReaRunner(tmp_path))
    browser = FakeBrowser()
    for url in ("http://192.168.1.5/admin", "http://localhost:3000/", "http://127.0.0.1:8000/", "ftp://demo.test/",
                "https://user:pw@demo-site.test/", "not a url"):
        with pytest.raises(XrayError):
            capture(url, kit, browser, audit, check_url=public_ok)
    assert not browser.entered
    assert [e["event"] for e in events(tmp_path)] == ["xray_capture_failed"] * 6
    assert "blocked" in events(tmp_path)[0]["reason"]
    assert "allow_local" in events(tmp_path)[1]["reason"]
    assert check_capture_url("http://localhost:3000/", allow_local=True, check_url=public_ok) == "localhost"
    assert check_capture_url("https://Demo-Site.test/x", check_url=public_ok) == "demo-site.test"


# ---- the full capture ----

def test_capture_collects_evidence_from_rea_and_jarvis(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    runner = ReaRunner(tmp_path)
    kit = make_kit(tmp_path, runner)
    browser = FakeBrowser()
    out = tmp_path / "job"
    cap = capture("https://demo-site.test/", kit, browser, audit, out_dir=out, check_url=public_ok)

    assert cap.host == "demo-site.test" and cap.started_at <= cap.finished_at
    assert browser.entered and browser.exited and browser.opened == ["https://demo-site.test/"]
    assert browser.scrolls == [16] and browser.to_top == 1
    names = [s.name for s in cap.steps]
    assert names == ["Open clean browser", "Load page", "Scroll page", "REA inspect-web-page", "REA analyze-web-bundle",
                     "Scroll to top", "REA capture-web-screenshot", "Asset log (performance entries)",
                     "Fingerprints (globals, banners, URLs)"]
    assert all(s.ok for s in cap.steps) and cap.ok
    assert {s.who for s in cap.steps} == {REA, JARVIS}
    assert [s.who for s in cap.steps if s.name.startswith("REA")] == [REA] * 3

    # REA commands: flags from --help, port and url passed, --json appended, observation window and sources
    cmds = [c[0] for c in runner.calls if "--help" not in c[0]]
    inspect = next(c for c in cmds if "inspect-web-page" in c)
    assert inspect[1].endswith("rea.js") and inspect[-1] == "--json"
    assert inspect[inspect.index("--url") + 1] == "https://demo-site.test/"
    assert inspect[inspect.index("--port") + 1] == "9444"
    assert inspect[inspect.index("--observation-ms") + 1] == "8000" and "--include-script-sources" in inspect
    shot = next(c for c in cmds if "capture-web-screenshot" in c)
    assert shot[shot.index("--output") + 1] == str(out / "screenshot.png")
    assert cap.screenshot == out / "screenshot.png" and cap.screenshot.is_file()
    assert cap.inspect["title"] == "Demo Studio" and cap.bundle["summary"]["bundler"] == "vite"

    # assets: 12 largest, biggest first, kinds from the extension
    assert len(cap.assets) == 12
    assert [a.bytes for a in cap.assets] == sorted((a.bytes for a in cap.assets), reverse=True)
    assert cap.assets[0].kind == "model" and cap.assets[0].url.endswith("model.glb")
    kinds = {a.url.rsplit("/", 1)[1]: a.kind for a in cap.assets}
    assert kinds["three.module.js"] == "script" and kinds["hero.webp"] == "image" and kinds["site.css"] == "style"
    assert kinds["Inter.woff2"] == "font"

    # fingerprints: REA saw the banners in script sources, Jarvis saw globals and script names
    fp = {(f.library, f.version): f for f in cap.fingerprints}
    assert fp[("Three.js", "r165")].who in (REA, JARVIS)
    assert fp[("GSAP", "3.12.5")].who == JARVIS and "window.gsap.version" in fp[("GSAP", "3.12.5")].evidence
    assert ("Lenis", "1.1.9") in fp and fp[("Lenis", "1.1.9")].who == REA
    assert ("Swiper", None) in fp and fp[("Swiper", None)].who == JARVIS
    assert ("Lenis", None) not in fp  # the versioned hit hides the bare one
    assert all(f.who in (REA, JARVIS) and f.evidence for f in cap.fingerprints)

    # files and audit
    saved = json.loads((out / "capture.json").read_text(encoding="utf-8"))
    assert saved["host"] == "demo-site.test" and len(saved["steps"]) == 9 and saved["screenshot"].endswith("screenshot.png")
    evs = events(tmp_path)
    assert [e["event"] for e in evs] == ["xray_capture_started", "xray_capture_finished"]
    assert evs[1]["failed"] == [] and evs[1]["fingerprints"] == len(cap.fingerprints) and evs[1]["screenshot"] is True


def test_digest_contract(tmp_path):
    kit = make_kit(tmp_path, ReaRunner(tmp_path))
    cap = capture("https://demo-site.test/", kit, FakeBrowser(), None, out_dir=tmp_path / "job", check_url=public_ok)
    text = cap.digest()
    assert len(text) <= 15000
    lines = text.splitlines()
    assert all(l.startswith(f"[{REA}] ") or l.startswith(f"[{JARVIS}] ") for l in lines if l.strip())
    assert lines[0] == f"[{JARVIS}] URL: https://demo-site.test/" and lines[1] == f"[{JARVIS}] Host: demo-site.test"
    assert lines[2].startswith(f"[{JARVIS}] Captured: ")
    headers = [l for l in lines if " == " in l]
    assert [h.split("==")[1].strip().split(" (")[0] for h in headers] == [
        "Steps", "Fingerprints", "Assets", "Bundle summary", "Page summary"]
    assert f"[{REA}] ok | REA | REA inspect-web-page" in text
    assert f"[{JARVIS}] ok | Jarvis | Scroll page | 16 wheel steps while REA observes" in text
    assert f"[{JARVIS}] GSAP 3.12.5 | Jarvis | window.gsap.version = 3.12.5" in text
    assert f"[{JARVIS}] model | 1,800,000 B | https://demo-site.test/assets/model.glb" in text
    assert f"[{REA}] summary.bundler: vite" in text and f"[{REA}] title: Demo Studio" in text
    assert f"[{REA}] metrics.domNodes: 1240" in text
    assert f"[{REA}] scripts[0].url: https://demo-site.test/assets/three.module.js" in text


def test_digest_is_cut_at_max_chars(tmp_path):
    cap = Capture(url="https://demo-site.test/", host="demo-site.test", started_at="t0", finished_at="t1",
                  inspect={"scripts": [{"url": f"https://demo-site.test/assets/{i}.js", "source": "x" * 300}
                                       for i in range(60)]})
    text = cap.digest()
    assert len(text) <= 15000 and text.endswith(f"[{JARVIS}] (digest cut at 15000 chars)")
    assert all(l.startswith("[") for l in text.splitlines() if l.strip())
    small = cap.digest(max_chars=400)
    assert len(small) <= 400 and small.endswith("chars)")


def test_rea_failure_is_a_failed_step_not_a_crash(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    kit = make_kit(tmp_path, ReaRunner(tmp_path, fail={"inspect-web-page", "capture-web-screenshot"}))
    cap = capture("https://demo-site.test/", kit, FakeBrowser(), audit, check_url=public_ok)
    failed = {s.name: s for s in cap.steps if not s.ok}
    assert set(failed) == {"REA inspect-web-page", "REA capture-web-screenshot"}
    assert failed["REA inspect-web-page"].detail == "Error: inspect-web-page failed in the fake"
    assert cap.inspect == {} and cap.screenshot is None and cap.bundle and cap.ok is False
    assert ("GSAP", "3.12.5") in {(f.library, f.version) for f in cap.fingerprints}  # Jarvis's own evidence survives
    assert f"[{REA}] FAILED | REA | REA inspect-web-page | Error: inspect-web-page failed in the fake" in cap.digest()
    assert events(tmp_path)[-1]["failed"] == ["REA inspect-web-page", "REA capture-web-screenshot"]


def test_flags_absent_from_help_are_not_sent(tmp_path):
    help_text = {"inspect-web-page": "  --url\n  --json\n", "analyze-web-bundle": "", "capture-web-screenshot": ""}
    runner = ReaRunner(tmp_path, help_text=help_text)
    kit = make_kit(tmp_path, runner)
    cap = capture("https://demo-site.test/", kit, FakeBrowser(), None, check_url=public_ok)
    inspect = next(c[0] for c in runner.calls if "inspect-web-page" in c[0] and "--help" not in c[0])
    assert "--observation-ms" not in inspect and "--include-script-sources" not in inspect and "--port" not in inspect
    assert "--url" in inspect
    bundle = next(c[0] for c in runner.calls if "analyze-web-bundle" in c[0] and "--help" not in c[0])
    assert bundle[2:] == ["analyze-web-bundle", "--json"]
    assert cap.ok


def test_page_load_failure_is_audited_and_raised(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    kit = make_kit(tmp_path, ReaRunner(tmp_path))
    browser = FakeBrowser(fail_open=True)
    with pytest.raises(XrayError, match="did not load"):
        capture("https://demo-site.test/", kit, browser, audit, check_url=public_ok)
    assert browser.exited and browser.scrolls == []
    evs = events(tmp_path)
    assert [e["event"] for e in evs] == ["xray_capture_started", "xray_capture_failed"]
    assert evs[1]["steps"] == 2


def test_capture_never_evaluates_anything_but_read_only_scripts(tmp_path):
    kit = make_kit(tmp_path, ReaRunner(tmp_path))
    browser = FakeBrowser()
    capture("https://demo-site.test/", kit, browser, None, check_url=public_ok)
    assert browser.evaluated == [ASSETS_JS, GLOBALS_JS, HTML_JS]
    for js in browser.evaluated:
        for forbidden in (".click(", ".submit(", "document.cookie", "localStorage", "fetch(", "XMLHttpRequest", "value ="):
            assert forbidden not in js


# ---- pieces ----

def test_assets_group_and_sort():
    assets = assets_from_entries(ENTRIES, top=3)
    assert [a.kind for a in assets] == ["model", "script", "image"]
    assert assets_from_entries([{"name": "", "bytes": 5}]) == []


def test_fingerprint_table():
    text = ("/* three.js r152 */ GSAP 3.11.4 postprocessing v6.35.2 lenis 1.0.42 locomotive-scroll 4.1.4 "
            "Swiper 11.0.5 @barba/core v2.9.7 React v18.2.0 Next.js v14.2.3 Vue v3.4.21 svelte 4.2.12 "
            "vite v5.2.0 webpack v5.91.0 draco_decoder.wasm basis_transcoder.js")
    found = {f.library: f.version for f in find_in_text(text, REA, "bundle.js")}
    assert found == {"Three.js": "r152", "GSAP": "3.11.4", "postprocessing": "6.35.2", "Lenis": "1.0.42",
                     "Locomotive Scroll": "4.1.4", "Swiper": "11.0.5", "Barba.js": "2.9.7", "React": "18.2.0",
                     "Next.js": "14.2.3", "Vue": "3.4.21", "Svelte": "4.2.12", "Vite": "5.2.0", "webpack": "5.91.0",
                     "Draco": None, "KTX2 / Basis": None}
    one = find_in_text(text, REA, "bundle.js")[0]
    assert one.who == REA and one.evidence.startswith("bundle.js: ")
    assert {(f.library, f.version) for f in from_globals({"THREE.REVISION": "165", "Vue.version": "3.4.0", "__svelte": "present"})} == {
        ("Three.js", "r165"), ("Vue", "3.4.0"), ("Svelte", None)}
    assert find_in_text("nothing here", JARVIS) == []


def test_flatten_is_bounded():
    lines = flatten({"a": {"b": [1, 2, 3], "c": "x" * 500, "d": [{"e": 1}, {"e": 2}]}})
    assert lines[0] == "a.b: 1, 2, 3" and lines[1].startswith("a.c: " + "x" * 160 + "... (500 chars)")
    assert lines[2:] == ["a.d[0].e: 1", "a.d[1].e: 2"]
    big = flatten({f"k{i}": i for i in range(1000)})
    assert len(big) == 61 and big[-1] == "(top): ... 940 more fields"
    deep = flatten({"rows": [{"a": i, "b": i} for i in range(500)]})
    assert len(deep) == 121 and deep[-1] == "rows: ... 440 more"


def test_offline_drill_checks_pass():
    checks = offline_checks()
    assert [c[0] for c in checks] == ["fingerprint Three.js r165", "fingerprint GSAP 3.12.5",
                                      "every digest line names its source", "digest respects max_chars"]
    assert all(ok for _, ok, _ in checks), checks
