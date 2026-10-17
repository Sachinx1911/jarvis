"""Dharma routing (PLAN.md 27.5 step 2, 27.8 decision 4): which office a piece of work belongs to.

Jarvis reads each workspace's `duties` (its dharma), its name, brief and project names, and matches
them against the words of the goal. Deterministic, no model: the same goal always routes the same
way, and the reasons can be shown and audited (law 3). Both scripts match, because every word is
reduced to the canonical romanized key the memory search already uses (jarvis/memory/translit.py):
"जाहिरात" and "jahirat" meet at one key.

Rules:
- personal is the default when nothing matches;
- sure when one workspace clearly wins (a duty or project word matched and the runner-up is more
  than 20% behind);
- unsure when two workspaces score within 20% of each other, or the best score is low (only a
  word of the brief matched): then Jarvis asks, with the candidates;
- a workspace Sachin set himself (/workspace, or the dashboard's choice) is never re-routed:
  callers do not call route() in that case.

The same word-overlap scoring picks a team inside a workspace (`pick_team`): the team whose purpose
and member briefs best match the goal leads the work; ties go to the first team.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from jarvis.memory.translit import roman_forms, words
from jarvis.workspaces.model import PERSONAL, Team, Workspace

# Weights per field: a duty names what the office is for; a project or the office's own name is almost
# as strong; a brief word is weak evidence on its own.
W_DUTY, W_NAME, W_PROJECT, W_BRIEF = 3, 2, 2, 1
MIN_SURE_SCORE = W_DUTY          # at least one duty/name/project word (weight >= 2 alone is "low")
CLOSE_MARGIN = 0.2               # runner-up within 20% of the best: ask
SURE_CONFIDENCE = 0.6

# Function words in English and romanized Marathi (canonical keys) that carry no routing meaning.
_STOP_RAW = {
    "the", "a", "an", "is", "are", "was", "be", "to", "of", "and", "or", "in", "on", "for", "my", "me", "i",
    "you", "it", "its", "this", "that", "with", "from", "by", "at", "as", "we", "our", "us", "do", "does",
    "please", "jarvis", "sir", "make", "get", "give", "find", "need", "want", "new", "all", "some", "about",
    "ahe", "ahet", "ani", "kar", "kara", "karne", "karun", "karaych", "karaycha", "karayche", "pahije", "hav",
    "havi", "have", "maza", "mazi", "maze", "mi", "tu", "la", "na", "cha", "chi", "che", "sathi", "madhe",
    "madhye", "var", "ek", "he", "te", "ha", "ti", "kay", "ka", "tar", "pan", "sang", "sanga", "de", "dya",
    "work", "task", "job", "kam", "team",
}
STOPWORDS = frozenset(_STOP_RAW | {k for w in _STOP_RAW for k in roman_forms(w)})


def key_map(text: str) -> dict[str, str]:
    """Canonical key -> the word as the user wrote it, without function words and very short keys."""
    out: dict[str, str] = {}
    for w in words(text or ""):
        for k in roman_forms(w):
            if len(k) >= 3 and k not in STOPWORDS:
                out.setdefault(k, w)
    return out


def keys(text: str) -> set[str]:
    return set(key_map(text))


def overlap(goal: dict[str, str], text: str) -> list[str]:
    """The goal's words (as written) that appear in `text`, sorted; a key matches a text key exactly or
    by stem (a prefix of 4+ letters), so "ads"/"ad" and "posts"/"post" meet."""
    hits: set[str] = set()
    for t in keys(text):
        for g, word in goal.items():
            if g == t or (len(g) >= 4 and t.startswith(g)) or (len(t) >= 4 and g.startswith(t)):
                hits.add(word)
    return sorted(hits)


@dataclass(frozen=True)
class Candidate:
    slug: str
    name: str
    score: int
    matched: tuple[str, ...] = ()     # "duties: ads, posts" style reasons

    def reason(self) -> str:
        return f"{self.name} ({'; '.join(self.matched) if self.matched else 'no match'})"


@dataclass(frozen=True)
class Routing:
    slug: str | None                 # the chosen workspace; None when Jarvis must ask
    confidence: float                # 0..1; sure at SURE_CONFIDENCE or above
    reasons: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)   # best first; personal is always offered

    @property
    def sure(self) -> bool:
        return self.slug is not None and self.confidence >= SURE_CONFIDENCE

    def line(self) -> str:
        """One line for the chat: "Routed to Digital Marketing (duties: ads)"."""
        if not self.sure:
            return "Which office is this for? " + ", ".join(
                f"{i}. {c.name}" for i, c in enumerate(self.candidates, 1))
        chosen = next((c for c in self.candidates if c.slug == self.slug), None)
        if chosen is None or not chosen.matched:
            return f"Routed to {chosen.name if chosen else self.slug} (default: nothing matched)"
        return f"Routed to {chosen.name} ({'; '.join(chosen.matched)})"


def score_workspace(goal_keys: dict[str, str], w: Workspace) -> Candidate:
    score, matched = 0, []
    duties = overlap(goal_keys, " ".join(w.duties))
    if duties:
        score += W_DUTY * len(duties)
        matched.append("duties: " + ", ".join(duties))
    name = overlap(goal_keys, f"{w.name} {w.slug.replace('-', ' ')}")
    if name:
        score += W_NAME * len(name)
        matched.append("name: " + ", ".join(name))
    projects = overlap(goal_keys, " ".join(p.replace("-", " ") for p in w.projects))
    if projects:
        score += W_PROJECT * len(projects)
        matched.append("projects: " + ", ".join(projects))
    brief = [k for k in overlap(goal_keys, w.brief) if k not in set(duties) | set(name) | set(projects)]
    if brief:
        score += W_BRIEF * len(brief)
        matched.append("brief: " + ", ".join(brief))
    return Candidate(w.slug, w.name, score, tuple(matched))


def route(goal: str, workspaces: Iterable[Workspace]) -> Routing:
    """Where `goal` belongs among the active workspaces. Deterministic; see the module docstring."""
    active = [w for w in workspaces if not w.archived]
    gk = key_map(goal)
    scored = sorted((score_workspace(gk, w) for w in active), key=lambda c: (-c.score, c.slug != PERSONAL, c.slug))
    personal = next((c for c in scored if c.slug == PERSONAL), Candidate(PERSONAL, "Personal", 0))
    companies = [c for c in scored if c.slug != PERSONAL]
    if not companies or not gk or (scored and scored[0].score == 0):
        why = "nothing matched a company's duties; personal is the default" if companies else "only the personal workspace exists"
        return Routing(PERSONAL, 1.0, [why], [personal] + companies[:3])

    best = scored[0]
    runner = scored[1] if len(scored) > 1 else Candidate(PERSONAL, "Personal", 0)
    offered = [c for c in scored if c.score > 0]
    if personal not in offered:
        offered.append(personal)
    if best.score < MIN_SURE_SCORE:
        conf = round(best.score / (2 * MIN_SURE_SCORE), 2)
        return Routing(None, conf, [f"weak match: {best.reason()}", "asking: the best score is low"], offered)
    margin = (best.score - runner.score) / best.score
    conf = round(0.5 + 0.5 * margin, 2)
    if margin < CLOSE_MARGIN:
        return Routing(None, conf, [f"close: {best.reason()} vs {runner.reason()}", "asking: two offices score alike"], offered)
    return Routing(best.slug, conf, [best.reason()], offered)


def pick_team(goal: str, teams: Iterable[Team]) -> Team | None:
    """The team of a workspace whose purpose, name and member briefs best match the goal; ties go to the
    first team (the store lists teams by file name). None when the workspace has no active team."""
    active = [t for t in teams if not t.archived]
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    gk = key_map(goal)
    best, best_score = active[0], -1
    for t in active:
        text = " ".join([t.name, t.purpose, *(f"{m.name} {m.brief}" for m in t.members)])
        s = len(overlap(gk, text))
        if s > best_score:
            best, best_score = t, s
    return best


__all__ = ["Candidate", "Routing", "SURE_CONFIDENCE", "key_map", "keys", "overlap", "pick_team", "route", "score_workspace"]
