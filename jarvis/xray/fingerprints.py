"""Library and version fingerprints from licence banners, script names and page globals.

Each pattern names the library and captures the version (group "v") when the text carries one.
Banners are matched against script sources or page HTML; globals come from a read-only
`Runtime.evaluate` in the clean browser. A fingerprint always records who saw the text
(REA or Jarvis) and the evidence snippet, so the teardown model can trace every claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEMVER = r"(?P<v>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)"
_I = re.IGNORECASE

# (library, compiled regex). Order matters only for the evidence shown; results are de-duplicated.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Three.js", re.compile(r"three(?:\.js)?\b[^\n]{0,40}?\b(?P<v>r\d{2,3})\b", _I)),
    ("Three.js", re.compile(r"\bREVISION\s*[=:]\s*['\"](?P<v>\d{2,3}[a-z]?)['\"]")),
    ("Three.js", re.compile(r"\bthree(?:\.module|\.min|\.cjs)?\.js\b(?!\S)", _I)),
    ("GSAP", re.compile(r"\bGSAP\b[^\n]{0,60}?\b" + SEMVER, _I)),
    ("GSAP", re.compile(r"\bgsap(?:\.min)?\.js\b", _I)),
    ("postprocessing", re.compile(r"\bpostprocessing\b[^\n]{0,30}?\bv?" + SEMVER, _I)),
    ("postprocessing", re.compile(r"\bpostprocessing(?:\.esm|\.min)?\.js\b", _I)),
    ("Lenis", re.compile(r"\blenis\b[^\n]{0,30}?\bv?" + SEMVER, _I)),
    ("Lenis", re.compile(r"\blenis(?:\.min|\.esm)?\.js\b", _I)),
    ("Locomotive Scroll", re.compile(r"locomotive[- ]scroll\b[^\n]{0,30}?\bv?" + SEMVER, _I)),
    ("Locomotive Scroll", re.compile(r"locomotive-scroll(?:\.min)?\.js\b", _I)),
    ("Swiper", re.compile(r"\bSwiper\b[^\n]{0,30}?\b" + SEMVER, _I)),
    ("Swiper", re.compile(r"\bswiper(?:-bundle)?(?:\.min)?\.js\b", _I)),
    ("Barba.js", re.compile(r"@barba/core\b[^\n]{0,30}?\bv?" + SEMVER, _I)),
    ("Barba.js", re.compile(r"\bbarba(?:\.umd|\.min)?\.js\b", _I)),
    ("React", re.compile(r"\bReact\b[^\n]{0,20}?\bv" + SEMVER)),
    ("React", re.compile(r"\breact(?:-dom)?(?:\.production|\.development)?(?:\.min)?\.js\b", _I)),
    ("Next.js", re.compile(r"\bNext\.js\b[^\n]{0,20}?\bv?" + SEMVER, _I)),
    ("Next.js", re.compile(r"/_next/static/", _I)),
    ("Vue", re.compile(r"\bVue(?:\.js)?\b[^\n]{0,20}?\bv" + SEMVER)),
    ("Vue", re.compile(r"\bvue(?:\.runtime)?(?:\.global|\.esm-browser)?(?:\.prod)?(?:\.min)?\.js\b", _I)),
    ("Svelte", re.compile(r"\bsvelte\b[^\n]{0,20}?\bv?" + SEMVER, _I)),
    ("Svelte", re.compile(r"__svelte\b|svelte-[a-z0-9]{6,}", _I)),
    ("Vite", re.compile(r"\bvite\b[^\n]{0,20}?\bv" + SEMVER, _I)),
    ("Vite", re.compile(r"/@vite/|\bvite/modulepreload-polyfill\b|__vite__", _I)),
    ("webpack", re.compile(r"\bwebpack\b[^\n]{0,20}?\bv" + SEMVER, _I)),
    ("webpack", re.compile(r"__webpack_require__|webpackChunk|webpackJsonp")),
    ("Draco", re.compile(r"\bdraco(?:_decoder|_wasm_wrapper|-decoder)?(?:\.js|\.wasm)\b", _I)),
    ("KTX2 / Basis", re.compile(r"\bbasis_transcoder(?:\.js|\.wasm)\b|\bKTX2Loader\b", _I)),
]

# Page globals (read-only) and how to turn each into a fingerprint. Collected by GLOBALS_JS in capture.py.
GLOBAL_LIBS: dict[str, tuple[str, str | None]] = {
    "THREE.REVISION": ("Three.js", "r{v}"),
    "gsap.version": ("GSAP", "{v}"),
    "Lenis": ("Lenis", None),
    "Swiper": ("Swiper", None),
    "barba": ("Barba.js", None),
    "React.version": ("React", "{v}"),
    "next.version": ("Next.js", "{v}"),
    "__NEXT_DATA__": ("Next.js", None),
    "Vue.version": ("Vue", "{v}"),
    "__svelte": ("Svelte", None),
    "__vite__": ("Vite", None),
    "webpackChunk": ("webpack", None),
    "LocomotiveScroll": ("Locomotive Scroll", None),
}


@dataclass
class Fingerprint:
    library: str
    version: str | None
    evidence: str
    who: str  # "REA" or "Jarvis"

    def line(self) -> str:
        return f"{self.library} {self.version or '(version not seen)'} | {self.who} | {self.evidence}"


def _snippet(text: str, start: int, end: int, width: int = 60) -> str:
    lo, hi = max(0, start - width // 3), min(len(text), end + width // 3)
    return " ".join(text[lo:hi].split())[:width + 20]


def find_in_text(text: str, who: str, source: str = "") -> list[Fingerprint]:
    """Fingerprints in a script source, licence banner or HTML. A versioned hit replaces a bare
    name hit for the same library; the first evidence per (library, version) is kept."""
    found: dict[tuple[str, str | None], Fingerprint] = {}
    for library, pattern in PATTERNS:
        for m in pattern.finditer(text):
            version = m.groupdict().get("v")
            if version and library == "Three.js" and version.isdigit():
                version = "r" + version
            key = (library, version)
            if key in found:
                continue
            evidence = _snippet(text, m.start(), m.end())
            if source:
                evidence = f"{source}: {evidence}"
            found[key] = Fingerprint(library, version, evidence, who)
            break  # one hit per pattern is enough evidence
    return dedupe(list(found.values()))


def from_globals(values: dict, who: str = "Jarvis") -> list[Fingerprint]:
    """Fingerprints from `{global name: value}` as read by GLOBALS_JS. A missing global is absent
    or None; a present one without a version is the string "present"."""
    out: list[Fingerprint] = []
    for name, (library, fmt) in GLOBAL_LIBS.items():
        value = values.get(name)
        if value in (None, "", False):
            continue
        version = None
        if fmt and value != "present":
            version = fmt.format(v=str(value))
        out.append(Fingerprint(library, version, f"window.{name} = {str(value)[:40]}", who))
    return dedupe(out)


def dedupe(items: list[Fingerprint]) -> list[Fingerprint]:
    """One entry per (library, version); a versioned entry hides the unversioned one for that library."""
    versioned = {f.library for f in items if f.version}
    seen: set[tuple[str, str | None]] = set()
    out: list[Fingerprint] = []
    for f in items:
        if f.version is None and f.library in versioned:
            continue
        key = (f.library, f.version)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
