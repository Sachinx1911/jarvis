"""One x-ray capture of a public web page (PLAN.md 18.1 item 3).

A capture is a T1 read-only observation: REA observes the page through the Chrome DevTools
Protocol while Jarvis scrolls; Jarvis then reads the asset log and library fingerprints with
read-only `Runtime.evaluate`. Nothing clicks, types, logs in or submits. Page content is
untrusted data and taints the session like any web page (PLAN 11.1); the caller sets the flag.

Egress: the only thing that leaves the machine is the address itself, and only after the same
public-address check the web tools use (private and loopback addresses are refused unless the
caller passes allow_local=True for a page served on this machine).

The result is a `Capture` whose `digest()` is the ordered evidence table that the teardown model
call receives. Every line of it says who saw the evidence: REA or Jarvis.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jarvis.control.audit import AuditLog
from jarvis.tools.web import WebError, _check_public_url
from jarvis.xray import XrayError
from jarvis.xray.fingerprints import Fingerprint, dedupe, find_in_text, from_globals
from jarvis.xray.kit import Kit

REA = "REA"
JARVIS = "Jarvis"
MAX_DIGEST = 15000
TOP_ASSETS = 12
SCROLL_STEPS = 16
OBSERVATION_MS = 8000
HTML_SCAN_CHARS = 300_000
SCRIPT_SCAN_CHARS = 200_000

# REA 6.5.0 flag names were not verified in the pack; the kit reads `rea <command> --help` once
# and the first candidate that exists is used (PLAN 18.1: "never depend on them blindly").
TARGET_FLAGS = ("--url", "--target-url", "--target", "--page")
PORT_FLAGS = ("--port", "--debug-port", "--debugging-port", "--cdp-port")
OBSERVATION_FLAGS = ("--observation-ms", "--observe-ms", "--duration-ms")
SOURCES_FLAGS = ("--include-script-sources", "--script-sources", "--sources")
OUTPUT_FLAGS = ("--output", "--out", "--path", "--file")

ASSET_KINDS = {
    "script": (".js", ".mjs", ".cjs"), "style": (".css",), "font": (".woff", ".woff2", ".ttf", ".otf", ".eot"),
    "image": (".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico"),
    "media": (".mp4", ".webm", ".mp3", ".ogg", ".wav", ".m4a", ".mov"),
    "model": (".glb", ".gltf", ".drc", ".ktx2", ".basis", ".hdr", ".exr", ".bin", ".wasm"),
    "data": (".json", ".xml", ".csv"),
}
INITIATOR_KINDS = {"script": "script", "css": "style", "link": "style", "img": "image", "video": "media",
                   "audio": "media", "font": "font", "fetch": "data", "xmlhttprequest": "data"}

# Read-only page scripts. They build plain JSON; nothing is changed on the page.
ASSETS_JS = """(() => {
  const out = [];
  for (const e of performance.getEntriesByType('resource')) {
    out.push({name: String(e.name).slice(0, 300), type: e.initiatorType || '',
              bytes: e.transferSize || e.encodedBodySize || e.decodedBodySize || 0});
  }
  return JSON.stringify(out.slice(0, 500));
})()"""
GLOBALS_JS = """(() => {
  const g = (f) => { try { const v = f(); return v === undefined || v === null ? null : (typeof v === 'string' || typeof v === 'number' ? String(v) : 'present'); } catch (e) { return null; } };
  return JSON.stringify({
    'THREE.REVISION': g(() => window.THREE && window.THREE.REVISION),
    'gsap.version': g(() => window.gsap && window.gsap.version),
    'Lenis': g(() => window.Lenis), 'Swiper': g(() => window.Swiper), 'barba': g(() => window.barba),
    'React.version': g(() => window.React && window.React.version),
    'next.version': g(() => window.next && window.next.version), '__NEXT_DATA__': g(() => window.__NEXT_DATA__),
    'Vue.version': g(() => window.Vue && window.Vue.version), '__svelte': g(() => window.__svelte),
    '__vite__': g(() => window.__vite__ || window.__vite_plugin_react_preamble_installed__),
    'webpackChunk': g(() => Object.keys(window).find(k => k.startsWith('webpackChunk'))),
    'LocomotiveScroll': g(() => window.LocomotiveScroll)
  });
})()"""
HTML_JS = f"(document.documentElement ? document.documentElement.outerHTML : '').slice(0, {HTML_SCAN_CHARS})"


@dataclass
class Step:
    name: str
    who: str  # REA or Jarvis
    ok: bool
    detail: str = ""

    def line(self) -> str:
        return f"{'ok' if self.ok else 'FAILED'} | {self.who} | {self.name}" + (f" | {self.detail}" if self.detail else "")


@dataclass
class Asset:
    kind: str
    url: str
    bytes: int

    def line(self) -> str:
        return f"{self.kind} | {self.bytes:,} B | {self.url}"


@dataclass
class Capture:
    """Everything one x-ray job saw. `digest()` is the contract with the teardown model call.

    Section order of digest(), fixed (the teardown prompt relies on it):
      1. URL/host/time     - `[Jarvis] URL: ...`, `[Jarvis] Host: ...`, `[Jarvis] Captured: <start> .. <end>`
      2. Steps             - one line per step: `[who] ok|FAILED | who | name | detail`
      3. Fingerprints      - `[who] <library> <version or (version not seen)> | who | evidence`
      4. Assets            - `[Jarvis] <kind> | <size> B | <url>` (12 largest, biggest first)
      5. Bundle summary    - flattened REA analyze-web-bundle JSON, every line `[REA] key: value`
      6. Page summary      - flattened REA inspect-web-page JSON, every line `[REA] key: value`
    Section headers are `[Jarvis] == <name> ==`. Every non-empty line starts with `[REA]` or
    `[Jarvis]`. The digest never exceeds max_chars; a cut ends with `[Jarvis] (digest cut at N chars)`.
    """
    url: str
    host: str
    started_at: str
    finished_at: str = ""
    steps: list[Step] = field(default_factory=list)
    inspect: dict = field(default_factory=dict)
    bundle: dict = field(default_factory=dict)
    screenshot: Path | None = None
    assets: list[Asset] = field(default_factory=list)
    fingerprints: list[Fingerprint] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["screenshot"] = str(self.screenshot) if self.screenshot else None
        return d

    def digest(self, max_chars: int = MAX_DIGEST) -> str:
        lines: list[str] = [f"[{JARVIS}] URL: {self.url}", f"[{JARVIS}] Host: {self.host}",
                            f"[{JARVIS}] Captured: {self.started_at} .. {self.finished_at or 'unfinished'}", ""]
        lines.append(f"[{JARVIS}] == Steps ==")
        lines += [f"[{s.who}] {s.line()}" for s in self.steps] or [f"[{JARVIS}] (no steps ran)"]
        lines += ["", f"[{JARVIS}] == Fingerprints (library, version, who, evidence) =="]
        lines += [f"[{f.who}] {f.line()}" for f in self.fingerprints] or [f"[{JARVIS}] (no library fingerprints seen)"]
        lines += ["", f"[{JARVIS}] == Assets (kind, size, url; {TOP_ASSETS} largest) =="]
        lines += [f"[{JARVIS}] {a.line()}" for a in self.assets] or [f"[{JARVIS}] (no resource entries seen)"]
        lines += ["", f"[{JARVIS}] == Bundle summary (from REA analyze-web-bundle) =="]
        lines += [f"[{REA}] {l}" for l in flatten(self.bundle)] or [f"[{REA}] (no bundle analysis)"]
        lines += ["", f"[{JARVIS}] == Page summary (from REA inspect-web-page) =="]
        lines += [f"[{REA}] {l}" for l in flatten(self.inspect)] or [f"[{REA}] (no page inspection)"]
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
        tail = f"\n[{JARVIS}] (digest cut at {max_chars} chars)"
        keep = text[: max_chars - len(tail)]
        keep = keep[: keep.rfind("\n")] if "\n" in keep else keep
        return keep + tail


# ---- helpers ----

def flatten(data: Any, prefix: str = "", max_lines: int = 400, max_value: int = 160, max_items: int = 60) -> list[str]:
    """`key.sub[2]: value` lines from a JSON object, depth-first, capped so a digest stays readable.
    Script sources and other long blobs are summarised by length."""
    out: list[str] = []

    def walk(node: Any, path: str) -> None:
        if len(out) >= max_lines:
            return
        if isinstance(node, dict):
            for k, v in list(node.items())[:max_items]:
                walk(v, f"{path}.{k}" if path else str(k))
            if len(node) > max_items:
                out.append(f"{path or '(top)'}: ... {len(node) - max_items} more fields")
        elif isinstance(node, list):
            if node and all(not isinstance(x, (dict, list)) for x in node) and len(node) <= 12:
                out.append(f"{path}: " + ", ".join(_short(x, 48) for x in node))
                return
            for i, v in enumerate(node[:max_items]):
                walk(v, f"{path}[{i}]")
            if len(node) > max_items:
                out.append(f"{path}: ... {len(node) - max_items} more")
        else:
            out.append(f"{path}: {_short(node, max_value)}")

    walk(data, prefix)
    if len(out) >= max_lines:
        out.append("... (more fields not shown)")
    return out


def _short(value: Any, n: int) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else f"{s[:n]}... ({len(s):,} chars)"


def check_capture_url(url: str, allow_local: bool = False,
                      check_url: Callable[[str], None] = _check_public_url) -> str:
    """Public http(s) only; localhost / loopback only with allow_local. Returns the host."""
    parsed = urllib.parse.urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise XrayError("x-ray needs a public http(s) web address")
    if parsed.username or parsed.password:
        raise XrayError("addresses with a user name or password are not allowed")
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
    if local:
        if not allow_local:
            raise XrayError("local addresses are only allowed for a page served on this machine (allow_local)")
        return host
    try:
        check_url(url)
    except WebError as e:
        raise XrayError(str(e)) from e
    return host


def asset_kind(url: str, initiator: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for kind, exts in ASSET_KINDS.items():
        if path.endswith(exts):
            return kind
    return INITIATOR_KINDS.get(initiator.lower(), "other")


def assets_from_entries(entries: list[dict], top: int = TOP_ASSETS) -> list[Asset]:
    assets = [Asset(asset_kind(str(e.get("name", "")), str(e.get("type", ""))), str(e.get("name", ""))[:300],
                    int(e.get("bytes") or 0)) for e in entries if e.get("name")]
    assets.sort(key=lambda a: (-a.bytes, a.url))
    return assets[:top]


def _script_sources(inspect: dict) -> list[tuple[str, str]]:
    """(name, source) pairs from REA's inspect JSON, whatever key it used for them."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, depth: int) -> None:
        if depth > 6 or len(out) > 200:
            return
        if isinstance(node, dict):
            src = node.get("source") or node.get("sourceText") or node.get("scriptSource")
            if isinstance(src, str) and len(src) > 20:
                out.append((str(node.get("url") or node.get("name") or node.get("scriptId") or "script"), src))
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(inspect, 0)
    return out


def _parse_json_text(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


# ---- the capture ----

def capture(url: str, kit: Kit, browser: Any, audit: AuditLog | None = None, out_dir: Path | None = None,
            allow_local: bool = False, observation_ms: int = OBSERVATION_MS, scroll_steps: int = SCROLL_STEPS,
            check_url: Callable[[str], None] = _check_public_url) -> Capture:
    """Observe `url` in the clean `browser` with REA from `kit`. `browser` is a not-yet-entered
    CleanBrowser (or a fake with the same open/scroll/scroll_to_top/evaluate/port surface)."""
    url = url.strip()
    try:
        host = check_capture_url(url, allow_local, check_url)
    except XrayError as e:
        if audit:
            audit.write("xray_capture_failed", url=url.split("?")[0][:200], reason=str(e))
        raise
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cap = Capture(url=url, host=host, started_at=started)
    if audit:
        audit.write("xray_capture_started", url=url.split("?")[0][:200], host=host)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    def step(name: str, who: str, fn: Callable[[], str]) -> bool:
        try:
            detail = fn()
            cap.steps.append(Step(name, who, True, detail or ""))
            return True
        except XrayError as e:
            cap.steps.append(Step(name, who, False, str(e)[:300]))
            return False

    try:
        with browser as b:
            cap.steps.append(Step("Open clean browser", JARVIS, True,
                                  f"fresh profile, loopback port {getattr(b, 'port', '?')}"
                                  + (", headless" if getattr(b, "headless", False) else "")))
            if not step("Load page", JARVIS, lambda: f"readyState {b.open(url)}"):
                raise XrayError("the page did not load: " + cap.steps[-1].detail)

            # REA observes while Jarvis scrolls.
            common = _target_args(kit, "inspect-web-page", url, b.port)
            obs_flag = kit.first_flag("inspect-web-page", OBSERVATION_FLAGS)
            src_flag = kit.first_flag("inspect-web-page", SOURCES_FLAGS)
            inspect_args = ["inspect-web-page", *common]
            if obs_flag:
                inspect_args += [obs_flag, str(observation_ms)]
            if src_flag:
                inspect_args.append(src_flag)
            box: dict[str, Any] = {}

            def run_inspect() -> None:
                try:
                    box["result"] = kit.rea(inspect_args, timeout=max(60.0, observation_ms / 1000 + 60))
                except XrayError as e:
                    box["error"] = e

            t = threading.Thread(target=run_inspect, name="rea-inspect", daemon=True)
            t.start()
            step("Scroll page", JARVIS, lambda: f"{b.scroll(scroll_steps)} wheel steps while REA observes")
            t.join()

            def inspect_done() -> str:
                if "error" in box:
                    raise box["error"]
                res = box.get("result")
                cap.inspect = res if isinstance(res, dict) else {"result": res}
                return _summary_detail(cap.inspect, obs_flag and f"observed {observation_ms} ms")

            step("REA inspect-web-page", REA, inspect_done)

            def bundle() -> str:
                res = kit.rea(["analyze-web-bundle", *_target_args(kit, "analyze-web-bundle", url, b.port)])
                cap.bundle = res if isinstance(res, dict) else {"result": res}
                return _summary_detail(cap.bundle, None)

            step("REA analyze-web-bundle", REA, bundle)
            step("Scroll to top", JARVIS, lambda: (b.scroll_to_top(), "wheel back to the top")[1])

            def shot() -> str:
                args = ["capture-web-screenshot", *_target_args(kit, "capture-web-screenshot", url, b.port)]
                target = (out_dir / "screenshot.png") if out_dir else None
                out_flag = kit.first_flag("capture-web-screenshot", OUTPUT_FLAGS)
                if target and out_flag:
                    args += [out_flag, str(target)]
                res = kit.rea(args)
                path = None
                if isinstance(res, dict):
                    for key in ("path", "file", "output", "screenshot"):
                        if isinstance(res.get(key), str):
                            path = Path(res[key])
                            break
                for cand in (path, target):
                    if cand and cand.is_file():
                        cap.screenshot = cand
                        return f"{cand.name} ({cand.stat().st_size:,} B)"
                return "REA reported a screenshot but no file was found"

            step("REA capture-web-screenshot", REA, shot)

            def assets() -> str:
                entries = _parse_json_text(b.evaluate(ASSETS_JS)) or []
                cap.assets = assets_from_entries(entries if isinstance(entries, list) else [])
                return f"{len(entries) if isinstance(entries, list) else 0} resource entries, {len(cap.assets)} kept"

            step("Asset log (performance entries)", JARVIS, assets)

            def fingerprints() -> str:
                found: list[Fingerprint] = []
                globs = _parse_json_text(b.evaluate(GLOBALS_JS)) or {}
                found += from_globals(globs if isinstance(globs, dict) else {}, JARVIS)
                html = b.evaluate(HTML_JS) or ""
                found += find_in_text(str(html)[:HTML_SCAN_CHARS], JARVIS, "page HTML")
                for name, src in _script_sources(cap.inspect):
                    found += find_in_text(src[:SCRIPT_SCAN_CHARS], REA, name[-80:])
                for a in cap.assets:
                    found += find_in_text(a.url, JARVIS, "asset URL")
                cap.fingerprints = dedupe(found)
                return f"{len(cap.fingerprints)} libraries fingerprinted"

            step("Fingerprints (globals, banners, URLs)", JARVIS, fingerprints)
    except XrayError as e:
        cap.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if audit:
            audit.write("xray_capture_failed", url=url.split("?")[0][:200], host=host, reason=str(e)[:300],
                        steps=len(cap.steps))
        raise
    cap.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if out_dir:
        (out_dir / "capture.json").write_text(json.dumps(cap.to_dict(), ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    if audit:
        audit.write("xray_capture_finished", url=url.split("?")[0][:200], host=host, steps=len(cap.steps),
                    failed=[s.name for s in cap.steps if not s.ok], fingerprints=len(cap.fingerprints),
                    assets=len(cap.assets), screenshot=bool(cap.screenshot))
    return cap


def _target_args(kit: Kit, command: str, url: str, port: int | None) -> list[str]:
    args: list[str] = []
    target = kit.first_flag(command, TARGET_FLAGS)
    if target:
        args += [target, url]
    port_flag = kit.first_flag(command, PORT_FLAGS)
    if port_flag and port:
        args += [port_flag, str(port)]
    return args


def _summary_detail(data: dict, extra: str | None) -> str:
    keys = ", ".join(list(data.keys())[:8]) or "empty"
    return f"{len(data)} top-level fields ({keys})" + (f"; {extra}" if extra else "")
