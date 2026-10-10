"""Weekly memory cleanup (PLAN.md 6.6). Deterministic: no model call.

1. Relative dates in active memories ("tomorrow", "next Monday", "udya",
   "पुढच्या सोमवारी") become absolute dates, counted from the memory's valid_from.
   The original text is kept in the evidence.
2. Duplicates: active memories of the same type and subject whose texts are
   near-identical (normalised text equal, or character-trigram Jaccard >= 0.9). The
   newest is kept; the others are superseded (never deleted). Pairs between 0.75 and
   0.9 are only listed in the report.
3. Archive: memories not used (or, if never used, created) for 90 days, except
   constraints and preferences.
4. MEMORY.md is rebuilt; MemoryStore keeps it under 200 lines (checked here).

Dry-run computes the same report and changes nothing. The report is written to
<home>/data/maintenance/<date>.md (<date>-dry-run.md for a dry run).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from jarvis.memory.model import Memory
from jarvis.memory.store import MEMORY_INDEX_MAX_LINES, MemoryRejected, MemoryStore

# ---------------------------------------------------------------- similarity


def normalize(text: str) -> str:
    """Lowercase, punctuation and symbols to spaces, whitespace collapsed (Devanagari safe)."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(" " if unicodedata.category(ch)[0] in "PSZC" else ch for ch in text)
    return " ".join(text.split())


def _grams(text: str) -> set[str]:
    padded = f" {text} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def similarity(a: str, b: str) -> float:
    """1.0 for equal normalised text, else trigram Jaccard on the normalised text."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return 1.0
    ga, gb = _grams(na), _grams(nb)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _text(m: Memory) -> str:
    return m.body.strip() or m.summary_en.strip() or m.name


def _newest_key(m: Memory) -> tuple[str, int]:
    digits = re.sub(r"\D", "", m.id)
    return (m.valid_from or "", int(digits) if digits else 0)


# ---------------------------------------------------------------- relative dates

_WEEKDAYS: dict[str, int] = {}
for _i, _names in enumerate([
    ("monday", "mon", "somvar", "somvaar", "सोमवार"),
    ("tuesday", "tue", "mangalvar", "mangalwar", "मंगळवार"),
    ("wednesday", "wed", "budhvar", "budhwar", "बुधवार"),
    ("thursday", "thu", "guruvar", "guruwar", "गुरुवार"),
    ("friday", "fri", "shukravar", "shukrawar", "शुक्रवार"),
    ("saturday", "sat", "shanivar", "shaniwar", "शनिवार"),
    ("sunday", "sun", "ravivar", "raviwar", "रविवार"),
]):
    for _n in _names:
        _WEEKDAYS[_n] = _i

_LATIN_DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|somvaa?ri?|mangal[vw]ari?|budh[vw]ari?|" \
             r"guru[vw]ari?|shukra[vw]ari?|shani[vw]ari?|ravi[vw]ari?)"
_DEV_DAY = r"(सोमवार|मंगळवार|बुधवार|गुरुवार|शुक्रवार|शनिवार|रविवार)(?:ी)?"
_L = r"(?<![\w'’])"          # Latin word start
_R = r"(?![\w'’])"           # Latin word end ("today's" is left alone)
_DL = r"(?<![ऀ-ॿ\w])"
_DR = r"(?![ऀ-ॿ\w])"


def _day_key(word: str) -> int:
    w = word.lower()
    if w in _WEEKDAYS:
        return _WEEKDAYS[w]
    w = re.sub(r"(?<=r)i$", "", w).replace("w", "v").replace("vaar", "var")  # somvari -> somvar
    return _WEEKDAYS[w]


def _next_weekday(base: date, weekday: int) -> date:
    """The first such day after base ("next Monday" said on a Monday = a week later)."""
    days = (weekday - base.weekday()) % 7
    return base + timedelta(days=days or 7)


# (pattern, function(match, base) -> date). Longer phrases first. Ambiguous words are left
# alone: Marathi "kal"/"काल" (yesterday or tomorrow), "parva"/"परवा", and "on Monday"
# (could be every Monday).
_RULES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(_L + r"(?:the\s+)?day\s+after\s+tomorrow" + _R, re.I), lambda m, d: d + timedelta(days=2)),
    (re.compile(_L + r"(?:next|this\s+coming|coming)\s+" + _LATIN_DAY + _R, re.I),
     lambda m, d: _next_weekday(d, _day_key(m.group(1)))),
    (re.compile(_L + r"(?:pudhch?ya|pudhcha|pudhil|yetya)\s+" + _LATIN_DAY + _R, re.I),
     lambda m, d: _next_weekday(d, _day_key(m.group(1)))),
    (re.compile(_DL + r"(?:पुढच्या|पुढील|येत्या)\s+" + _DEV_DAY + _DR), lambda m, d: _next_weekday(d, _WEEKDAYS[m.group(1)])),
    (re.compile(_L + r"in\s+(\d{1,2})\s+days?" + _R, re.I), lambda m, d: d + timedelta(days=int(m.group(1)))),
    (re.compile(_L + r"tomorrow" + _R, re.I), lambda m, d: d + timedelta(days=1)),
    (re.compile(_L + r"yesterday" + _R, re.I), lambda m, d: d - timedelta(days=1)),
    (re.compile(_L + r"(?:today|tonight)" + _R, re.I), lambda m, d: d),
    (re.compile(_L + r"udy(?:a|aa)" + _R, re.I), lambda m, d: d + timedelta(days=1)),
    (re.compile(_L + r"aaj" + _R, re.I), lambda m, d: d),
    (re.compile(_DL + r"उद्या" + _DR), lambda m, d: d + timedelta(days=1)),
    (re.compile(_DL + r"आज" + _DR), lambda m, d: d),
]


def resolve_relative_dates(text: str, base: date) -> str:
    """Replace relative date words with ISO dates counted from `base`. Deterministic."""
    for pattern, fn in _RULES:
        text = pattern.sub(lambda m, fn=fn: fn(m, base).isoformat(), text)
    return text


# ---------------------------------------------------------------- report


@dataclass
class CleanupReport:
    day: date
    dry_run: bool
    checked: int = 0
    dates_fixed: list[tuple[str, str, str]] = field(default_factory=list)    # (id, before, after)
    superseded: list[tuple[str, str, float]] = field(default_factory=list)   # (old id, kept id, similarity)
    borderline: list[tuple[str, str, float]] = field(default_factory=list)   # (id, id, similarity)
    archived: list[tuple[str, str]] = field(default_factory=list)            # (id, last used or created)
    errors: list[str] = field(default_factory=list)
    memory_md_lines: int = 0
    path: Path | None = None

    def counts(self) -> dict[str, int]:
        return {"checked": self.checked, "dates_fixed": len(self.dates_fixed), "superseded": len(self.superseded),
                "borderline": len(self.borderline), "archived": len(self.archived), "errors": len(self.errors)}

    def summary(self) -> str:
        c = self.counts()
        head = "Memory cleanup" + (" (dry run, nothing changed)" if self.dry_run else "")
        return (f"{head}: {c['checked']} active memories checked; {c['dates_fixed']} relative date(s) fixed, "
                f"{c['superseded']} duplicate(s) superseded, {c['borderline']} borderline pair(s) to review, "
                f"{c['archived']} archived; MEMORY.md {self.memory_md_lines} lines.")

    def markdown(self) -> str:
        lines = [f"# Memory cleanup {self.day.isoformat()}" + (" (dry run)" if self.dry_run else ""), "",
                 self.summary(), ""]

        def section(title: str, items: list[str]) -> None:
            lines.append(f"## {title}")
            lines.extend(items or ["- none"])
            lines.append("")

        section("Relative dates made absolute", [f"- {i}: {b!r} -> {a!r}" for i, b, a in self.dates_fixed])
        section("Duplicates superseded (newest kept)", [f"- {o} -> kept {k} (similarity {s:.2f})"
                                                        for o, k, s in self.superseded])
        section("Borderline pairs (not merged; review by hand)", [f"- {a} ~ {b} (similarity {s:.2f})"
                                                                  for a, b, s in self.borderline])
        section("Archived (unused)", [f"- {i} (last {when})" for i, when in self.archived])
        if self.errors:
            section("Errors", [f"- {e}" for e in self.errors])
        lines.append(f"MEMORY.md: {self.memory_md_lines} lines (limit {MEMORY_INDEX_MAX_LINES}).")
        return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- cleanup


class MemoryCleanup:
    def __init__(self, memory: MemoryStore, home: Path, today: date, audit: Any = None,
                 settings: dict[str, Any] | None = None):
        s = settings or {}
        self.memory = memory
        self.home = home
        self.today = today
        self.audit = audit
        self.dup = float(s.get("duplicate_similarity", 0.9))
        self.borderline = float(s.get("borderline_similarity", 0.75))
        self.archive_days = int(s.get("archive_after_days", 90))
        self.keep_types = set(s.get("keep_types") or ["constraint", "preference"])

    def _log(self, event: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.write(event, **fields)

    def _save(self, mem: Memory, report: CleanupReport, what: str) -> bool:
        if report.dry_run:
            return True
        try:
            self.memory.update(mem)
            return True
        except (MemoryRejected, ValueError, KeyError) as e:
            report.errors.append(f"{mem.id}: {what} not saved ({e})")
            return False

    def run(self, dry_run: bool = False, write_report: bool = True) -> CleanupReport:
        report = CleanupReport(self.today, dry_run)
        active = self.memory.list(status="active")
        report.checked = len(active)

        # 1. relative dates -> absolute
        for m in active:
            try:
                base = date.fromisoformat(m.valid_from)
            except ValueError:
                continue
            new_body = resolve_relative_dates(m.body, base)
            new_summary = resolve_relative_dates(m.summary_en, base)
            if new_body == m.body and new_summary == m.summary_en:
                continue
            note = []
            if new_body != m.body:
                report.dates_fixed.append((m.id, m.body, new_body))
                note.append(f"original body: {m.body}")
            if new_summary != m.summary_en:
                report.dates_fixed.append((m.id, m.summary_en, new_summary))
                note.append(f"original summary: {m.summary_en}")
            m.evidence = (f"{m.evidence} | [cleanup {self.today.isoformat()}: relative dates resolved from "
                          f"valid_from {m.valid_from}; {'; '.join(note)}]")
            m.body, m.summary_en = new_body, new_summary
            if self._save(m, report, "date fix"):
                self._log("memory_cleanup_date", id=m.id, dry_run=dry_run)

        # 2. duplicates (same type and subject)
        groups: dict[tuple[str, str], list[Memory]] = {}
        for m in active:
            groups.setdefault((m.type, normalize(m.subject)), []).append(m)
        gone: set[str] = set()
        for members in groups.values():
            members.sort(key=_newest_key, reverse=True)
            kept: list[Memory] = []
            for m in members:
                best, score = None, 0.0
                for k in kept:
                    s = similarity(_text(m), _text(k))
                    if s > score:
                        best, score = k, s
                if best is not None and score >= self.dup:
                    report.superseded.append((m.id, best.id, round(score, 3)))
                    gone.add(m.id)
                    m.status, m.superseded_by, m.valid_until = "superseded", best.id, self.today.isoformat()
                    if self._save(m, report, "supersede"):
                        self._log("memory_cleanup_duplicate", id=m.id, kept=best.id, similarity=round(score, 3),
                                  dry_run=dry_run)
                else:
                    kept.append(m)
            for i, a in enumerate(kept):
                for b in kept[i + 1:]:
                    s = similarity(_text(a), _text(b))
                    if self.borderline <= s < self.dup:
                        report.borderline.append((a.id, b.id, round(s, 3)))

        # 3. archive unused (constraints and preferences stay)
        cutoff = self.today - timedelta(days=self.archive_days)
        for m in active:
            if m.id in gone or m.type in self.keep_types:
                continue
            last = m.last_used or m.valid_from
            try:
                when = date.fromisoformat(last)
            except ValueError:
                continue
            if when < cutoff:
                report.archived.append((m.id, last))
                if not dry_run:
                    self.memory.archive(m.id)
                self._log("memory_cleanup_archive", id=m.id, last=last, dry_run=dry_run)

        # 4. MEMORY.md (MemoryStore caps it at 200 lines)
        if dry_run:
            index = self.memory.root / "MEMORY.md"
            report.memory_md_lines = len(index.read_text(encoding="utf-8").splitlines()) if index.exists() else 0
        else:
            path = self.memory.write_memory_md()
            report.memory_md_lines = len(path.read_text(encoding="utf-8").splitlines())
        if report.memory_md_lines > MEMORY_INDEX_MAX_LINES:
            report.errors.append(f"MEMORY.md has {report.memory_md_lines} lines (limit {MEMORY_INDEX_MAX_LINES})")

        if write_report:
            folder = self.home / "data" / "maintenance"
            folder.mkdir(parents=True, exist_ok=True)
            report.path = folder / f"{self.today.isoformat()}{'-dry-run' if dry_run else ''}.md"
            report.path.write_text(report.markdown(), encoding="utf-8")
        self._log("memory_cleanup", dry_run=dry_run, report=str(report.path) if report.path else None,
                  **report.counts())
        return report


def latest_report(home: Path) -> Path | None:
    folder = home / "data" / "maintenance"
    files = sorted(folder.glob("*.md")) if folder.exists() else []
    return files[-1] if files else None
