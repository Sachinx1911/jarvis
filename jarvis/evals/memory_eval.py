"""Memory retrieval eval (research 2026-10-10, topic 4: "how to evaluate").

Synthetic fixtures in tests/evals/memory/cases.yaml, LongMemEval-style categories:
single-fact, preference, knowledge-update, multi-session, temporal, unanswerable.

Two metrics, measured separately:
- Offline retrieval (no model, deterministic): Recall@5 of the gold evidence among the top 5
  memories plus the top 5 past-chat sessions that the context builder retrieves. Also
  memory Recall@5, session Recall@5 and the stale rate (a superseded session ranked above
  the current one). run_offline() measures every ablation step, one change at a time.
- Live answers (opt-in, real model through the normal routes): answer accuracy with simple
  string checks; unanswerable questions pass only when Jarvis declines; the stale-answer
  rate on knowledge-update questions is reported on its own line.

Each run builds a throwaway Jarvis home: real memory and chats are never touched.
"""

from __future__ import annotations

import re

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import yaml

from jarvis.core.context import ContextBuilder, RetrievalOptions
from jarvis.db import Store
from jarvis.memory.model import Memory
from jarvis.memory.quiet import mark_extracted
from jarvis.memory.store import MemoryStore
from jarvis.paths import REPO_ROOT

CASES_FILE = REPO_ROOT / "tests" / "evals" / "memory" / "cases.yaml"
K = 5
SESSION_POOL = 25   # past-chat messages fetched to find the top K distinct sessions

# Ablation switches: (name, script_forms, time_aware, session_facts, excerpts).
# Cumulative order: what each change adds on top of the ones before it.
STEPS: list[tuple[str, dict[str, bool]]] = [
    ("baseline (memories only)", dict(script_forms=False, time_aware=False, session_facts=False, excerpts=False)),
    ("+ raw excerpts (4)", dict(script_forms=False, time_aware=False, session_facts=False, excerpts=True)),
    ("+ both scripts (1)", dict(script_forms=True, time_aware=False, session_facts=False, excerpts=True)),
    ("+ time-aware (2)", dict(script_forms=True, time_aware=True, session_facts=False, excerpts=True)),
    ("+ session facts (3) = all", dict(script_forms=True, time_aware=True, session_facts=True, excerpts=True)),
]
FULL = STEPS[-1][1]
LEAVE_ONE_OUT = [(f"all - {name}", {**FULL, name: False})
                 for name in ("script_forms", "time_aware", "session_facts", "excerpts")]

ABSTAIN = ("don't know", "do not know", "don't remember", "do not remember", "not sure", "no record",
           "haven't told", "have not told", "didn't tell", "did not tell", "no information", "not mentioned",
           "माहित नाही", "माहीत नाही", "आठवत नाही", "mahit nahi", "mahiti nahi", "athvat nahi", "सांगितलं नाही",
           "sangitla nahi", "सांगितले नाही",
           # "I don't have it" / "not saved" / "no note of it", in English, romanized and Devanagari Marathi
           "don't have", "do not have", "not saved", "never saved", "wasn't saved", "no note of",
           "नोंद नाही", "nond nahi", "memory madhe nahi", "मेमरीत नाही", "माहिती नाही", "माझ्याकडे नाही",
           "mazyakade nahi", "सापडले नाही", "sapadla nahi")

# Words that put a value in the past ("before that it was the 299 plan"). In a knowledge update,
# naming the old value as history is fine; presenting it as the current value is stale.
# Only explicit "before/earlier" words: a bare "was" ("your plan was changed to 299") can present the
# old value as current, so it does not count.
PAST_MARKERS = ("before", "earlier", "previous", "used to", "moved from", "switched from", "changed from",
                "until ", "former", "adhi", "aadhi", "pahile", "purvi", "agodar", "पूर्वी", "आधी", "पहिले", "अगोदर")


# ---- fixtures ----

def load_cases(path: Path = CASES_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def today_of(cases: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(cases["today"]).replace(hour=12)


def _utc(local: str) -> str:
    """Fixture times are local; messages.ts is UTC 'YYYY-MM-DD HH:MM:SS' like SQLite datetime('now')."""
    return datetime.fromisoformat(local).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_home(home: Path, cases: dict[str, Any], script_forms: bool = True,
               time_aware: bool = True) -> tuple[Store, MemoryStore]:
    """A throwaway Jarvis home holding the fixture memories and past chats."""
    store = Store(home / "data" / "jarvis.db")
    memory = MemoryStore(home, store, script_forms=script_forms, time_aware=time_aware)
    by_session: dict[str, list[str]] = {}
    for raw in cases["memories"]:
        data = {k: v for k, v in raw.items() if k != "session"}
        memory.save(Memory(**data))
        if raw.get("session"):
            by_session.setdefault(raw["session"], []).append(raw["id"])
    conn = store.conn
    for sess in cases["sessions"]:
        ts = _utc(sess["time"])
        for role, text in sess["messages"]:
            parts = json.dumps([{"type": "TextPart", "text": text}], ensure_ascii=False)
            cur = conn.execute("INSERT INTO messages (session_id, ts, role, parts) VALUES (?, ?, ?, ?)",
                               (sess["id"], ts, role, parts))
            conn.execute("INSERT INTO session_text (message_id, session_id, role, ts, text) VALUES (?, ?, ?, ?, ?)",
                         (cur.lastrowid, sess["id"], role, ts, text))
        conn.commit()
        if sess["id"] in by_session:
            mark_extracted(conn, sess["id"], [("ADD", mid) for mid in by_session[sess["id"]]])
    return store, memory


# ---- offline retrieval ----

@dataclass
class QuestionResult:
    id: str
    category: str
    script: str
    memories: list[str]
    sessions: list[str]
    groups: int
    groups_hit: int
    gold_memories: int
    memories_hit: int
    gold_sessions: int
    sessions_hit: int
    stale_above: bool | None


@dataclass
class StepResult:
    name: str
    questions: list[QuestionResult] = field(default_factory=list)

    def _ratio(self, num: str, den: str, category: str | None = None) -> float | None:
        qs = [q for q in self.questions if category is None or q.category == category]
        d = sum(getattr(q, den) for q in qs)
        return sum(getattr(q, num) for q in qs) / d if d else None

    def recall(self, category: str | None = None) -> float | None:
        return self._ratio("groups_hit", "groups", category)

    def memory_recall(self) -> float | None:
        return self._ratio("memories_hit", "gold_memories")

    def session_recall(self) -> float | None:
        return self._ratio("sessions_hit", "gold_sessions")

    def stale_rate(self) -> float | None:
        qs = [q for q in self.questions if q.stale_above is not None]
        return sum(q.stale_above for q in qs) / len(qs) if qs else None


def _split(ids: list[str]) -> tuple[set[str], set[str]]:
    mems = {i for i in ids if i.startswith("m-")}
    return mems, set(ids) - mems


def evaluate_question(builder: ContextBuilder, q: dict[str, Any], now: datetime) -> QuestionResult:
    hits, found = builder.retrieve(q["query"], now, k=K, excerpts=SESSION_POOL)
    mem_ids = [h.memory.id for h in hits][:K]
    sessions = list(dict.fromkeys(h.session_id for h in found))[:K]
    retrieved = set(mem_ids) | set(sessions)
    groups = [list(g) for g in q.get("evidence") or []]
    gold_m, gold_s = _split([i for g in groups for i in g])
    stale_above = None
    stale = q.get("stale") or []
    if stale and builder.options.excerpts:   # no past-chat search: nothing to be stale ("-")
        _, stale_s = _split(stale)
        rank = {sid: i for i, sid in enumerate(sessions)}
        best_gold = min((rank[s] for s in gold_s if s in rank), default=None)
        best_stale = min((rank[s] for s in stale_s if s in rank), default=None)
        stale_above = best_stale is not None and (best_gold is None or best_stale < best_gold)
    return QuestionResult(
        id=q["id"], category=q["category"], script=q.get("script", ""), memories=mem_ids, sessions=sessions,
        groups=len(groups), groups_hit=sum(1 for g in groups if set(g) & retrieved),
        gold_memories=len(gold_m), memories_hit=len(gold_m & set(mem_ids)),
        gold_sessions=len(gold_s), sessions_hit=len(gold_s & set(sessions)), stale_above=stale_above,
    )


def run_step(name: str, flags: dict[str, bool], cases: dict[str, Any] | None = None,
             category: str | None = None) -> StepResult:
    cases = cases or load_cases()
    now = today_of(cases)
    result = StepResult(name)
    with tempfile.TemporaryDirectory(prefix="jarvis-memeval-") as tmp:
        home = Path(tmp)
        store, memory = build_home(home, cases, flags["script_forms"], flags["time_aware"])
        try:
            builder = ContextBuilder(home, memory, None)
            builder.options = RetrievalOptions(time_aware=flags["time_aware"],
                                               session_facts=flags["session_facts"], excerpts=flags["excerpts"])
            builder.session_id = "eval-none"
            for q in cases["questions"]:
                if category and q["category"] != category:
                    continue
                result.questions.append(evaluate_question(builder, q, now))
        finally:
            store.close()
    return result


def run_offline(cases_path: Path = CASES_FILE, category: str | None = None,
                ablation: bool = True) -> list[StepResult]:
    cases = load_cases(cases_path)
    steps = STEPS + LEAVE_ONE_OUT if ablation else [STEPS[-1]]
    return [run_step(name, flags, cases, category) for name, flags in steps]


def _pct(x: float | None) -> str:
    return "  -  " if x is None else f"{100 * x:5.1f}"


CATEGORIES = ("single-fact", "preference", "knowledge-update", "multi-session", "temporal")


def format_offline(steps: list[StepResult]) -> str:
    head = (f"{'step':30} {'R@5':>5} {'mem':>5} {'sess':>5} {'stale':>5}  "
            + " ".join(f"{c[:6]:>6}" for c in CATEGORIES))
    lines = ["Memory retrieval, offline Recall@5 (%; evidence groups in top-5 memories + top-5 sessions)", head]
    for s in steps:
        lines.append(f"{s.name:30} {_pct(s.recall())} {_pct(s.memory_recall())} {_pct(s.session_recall())} "
                     f"{_pct(s.stale_rate())}  " + " ".join(f"{_pct(s.recall(c)):>6}" for c in CATEGORIES))
    full = next((s for s in steps if s.name == STEPS[-1][0]), steps[-1])
    misses = [q for q in full.questions if q.groups and q.groups_hit < q.groups]
    if misses:
        lines.append("Missed with all changes on: " + ", ".join(f"{q.id} ({q.groups_hit}/{q.groups})" for q in misses))
    return "\n".join(lines)


# ---- live answers (opt-in) ----

@dataclass
class LiveResult:
    id: str
    category: str
    script: str
    passed: bool
    stale: bool
    detail: str
    output: str = ""


def _clauses(low: str) -> list[str]:
    return [c.strip() for c in re.split(r"[.!?;()\n।]|\s-\s|^-\s", low) if c.strip()]


# Romanized words that contain a past marker but are not past words ("kadhi" = when).
NOT_PAST_WORDS = re.compile(r"(?<![a-z])kadhi[a-z]*")


def _has_past_marker(clause: str) -> bool:
    """Romanized Marathi attaches "adhi" to the word before it ("tyaadhi" = before that), so Latin
    markers must end at a word edge but may start inside a word; known false words are removed first.
    Devanagari markers match as substrings (vowel signs are not word characters)."""
    latin = NOT_PAST_WORDS.sub(" ", clause)
    for m in PAST_MARKERS:
        if m.isascii():
            if re.search(rf"{re.escape(m.strip())}(?![a-z])", latin):
                return True
        elif m in clause:
            return True
    return False


def _as_current(value: str, low: str) -> bool:
    """The value appears in some clause that does not put it in the past."""
    v = value.lower()
    return any(v in c and not _has_past_marker(c) for c in _clauses(low))


def check_answer(q: dict[str, Any], output: str) -> tuple[bool, bool, str]:
    """(passed, stale, detail)."""
    low = output.lower()
    # Knowledge updates, and questions marked history_ok, may name an old value as history.
    history_ok = q["category"] == "knowledge-update" or bool(q.get("history_ok"))
    present = (lambda v: _as_current(v, low)) if history_ok else (lambda v: v.lower() in low)
    stale = any(present(v) for v in q.get("stale_values", []))
    if q["category"] == "unanswerable":
        ok = any(p in low for p in ABSTAIN)
        return ok, False, "declined" if ok else "answered instead of declining"
    checks = q.get("answer", {})
    if checks.get("contains_any") and not any(s.lower() in low for s in checks["contains_any"]):
        return False, stale, f"missing any of {checks['contains_any']}"
    bad = [s for s in checks.get("not_contains", []) if present(s)]
    if bad:
        return False, stale, f"contains {bad}"
    return True, stale, "ok"


def run_live(rt, provider_name: str | None = None, category: str | None = None,
             cases_path: Path = CASES_FILE) -> tuple[list[LiveResult], Path]:
    """Ask every question through a normal ChatSession (real model, main_chat route)."""
    from jarvis.control.audit import AuditLog
    from jarvis.core.chat import ROUTE, ChatSession
    from jarvis.evals.runner import _git_commit
    from jarvis.providers import make_provider
    from jarvis.providers.base import ProviderError
    from jarvis.routing.policy import decide

    cases = load_cases(cases_path)
    now = today_of(cases)
    d = decide(rt.config, ROUTE, provider_name)
    results: list[LiveResult] = []
    for q in cases["questions"]:
        if category and q["category"] != category:
            continue
        with tempfile.TemporaryDirectory(prefix="jarvis-memeval-") as tmp:
            home = Path(tmp)
            store, memory = build_home(home, cases)
            try:
                session = ChatSession(rt.config, make_provider(d.provider, rt.config), d, store,
                                      AuditLog(home / "data" / "audit.jsonl"), now=lambda: now, home=home,
                                      memory=memory)
                output = session.send(q["query"])
                ok, stale, detail = check_answer(q, output)
            except ProviderError as e:
                output, ok, stale, detail = "", False, False, f"provider error: {e}"
            finally:
                store.close()
        results.append(LiveResult(q["id"], q["category"], q.get("script", ""), ok, stale, detail, output))
    out_dir = rt.paths.data / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-memory-{d.provider}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"suite": "memory", "provider": d.provider, "model": d.model,
                                     "date": stamp, "commit": _git_commit()}}) + "\n")
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return results, path


def format_live(results: list[LiveResult]) -> str:
    lines = [f"{'PASS' if r.passed else 'FAIL'} {r.id} [{r.category}/{r.script}] {r.detail}" for r in results]
    if results:
        lines.append(f"Answer accuracy: {sum(r.passed for r in results)}/{len(results)}")
        ku = [r for r in results if r.category == "knowledge-update"]
        if ku:
            lines.append(f"Stale-answer rate (knowledge-update): {sum(r.stale for r in ku)}/{len(ku)}")
        un = [r for r in results if r.category == "unanswerable"]
        if un:
            lines.append(f"Abstention (unanswerable declined): {sum(r.passed for r in un)}/{len(un)}")
    return "\n".join(lines)


# ---- CLI entry (`jarvis eval --suite memory [--live] [--provider P] [--category C]`) ----

def run_cli(args: Any, out: TextIO) -> int:
    category = getattr(args, "category", None)
    if not getattr(args, "live", False):
        print(format_offline(run_offline(category=category)), file=out)
        return 0
    from jarvis.core.runtime import open_runtime

    rt = open_runtime()
    try:
        results, path = run_live(rt, getattr(args, "provider", None), category)
    finally:
        rt.close()
    print(format_live(results), file=out)
    print(f"Results: {path}", file=out)
    return 0 if results and all(r.passed for r in results) else 1
