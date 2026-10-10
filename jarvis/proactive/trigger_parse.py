"""Chat text -> trigger draft. The draft is shown to the user and saved only after a yes.

Deterministic rules only (English, romanized Marathi, a few Devanagari words). When the
rules cannot read the text the parser asks a question instead of guessing; there is no
model fallback, because a wrong trigger fires on its own, unattended.

Examples it reads:
  "when a new file arrives in workspace/inbox summarize it"
  "jar laptop chi kimmat 75000 khali geli tar sang https://www.croma.com/..."
  "when I get an email from boss@example.com tell me"
  "15 minutes before a meeting remind me"
  "tell me when there are new results for 'new laptop launch India'"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCES = ("file_new", "web_price", "email_from", "calendar_soon", "web_search_new")
ACTIONS = ("notify", "prompt", "skill", "agent")
OUTPUTS = ("telegram", "file", "both")

URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")
EMAIL_RE = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[A-Za-z]{2,}")

# "tell me" in English and Marathi: the action is a plain notification, no model needed.
_NOTIFY = re.compile(
    r"^(?:please\s+|pls\s+|mala\s+|मला\s+)?(?:just\s+)?(?:tell|notify|alert|ping|message|inform|remind)\s*(?:me)?\b"
    r"|^(?:let me know|send me a message)\b"
    r"|^(?:mala\s+|मला\s+)?(?:sang|saang|sanga|kalav|kalva|kalwa|kalaw|सांग|सांगा|कळव|कळवा)\b",
    re.IGNORECASE)
_FILLER = re.compile(r"^(?:then|and|,|;|:|-|tar|तर|to|please|pls|arrives?|comes?(?: in)?|appears?|lands?|"
                     r"(?:is|are|gets?) (?:added|received|saved|in)|aala|aali|ala|ali|आला|आली)(?:\s+|\s*[,;:]\s*)",
                     re.IGNORECASE)
_COND_START = re.compile(r"\b(?:when(?:ever)?|if|once|jar|जर)\b", re.IGNORECASE)

_EXT_WORDS = {"pdf": "*.pdf", "csv": "*.csv", "txt": "*.txt", "text": "*.txt", "word": "*.docx", "docx": "*.docx",
              "excel": "*.xlsx", "xlsx": "*.xlsx", "image": "*.jpg", "photo": "*.jpg", "jpg": "*.jpg",
              "png": "*.png", "markdown": "*.md", "md": "*.md"}


class TriggerParseError(ValueError):
    """The text could not be read as a trigger; .question says what to ask the user."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


class TriggerInvalid(ValueError):
    """A trigger that must not be saved (outside the allowed folders, Amazon/Flipkart, ...)."""


@dataclass
class TriggerDraft:
    name: str
    source: str
    condition: dict[str, Any]
    action: str = "notify"          # notify | prompt | skill | agent
    target: str = ""                # skill or agent name
    input: str = ""                 # the prompt / task text
    output: str = "telegram"
    every_s: int = 300
    cooldown_s: int = 600
    description: str = ""
    read_by: str = "rules"          # rules | explicit

    def show(self) -> str:
        what = {"notify": "send you a message (no AI model)",
                "prompt": f"ask Jarvis: {self.input!r}",
                "skill": f"run skill {self.target!r} with {self.input!r}",
                "agent": f"give agent {self.target!r} the task {self.input!r}"}[self.action]
        cond = ", ".join(f"{k}={v}" for k, v in self.condition.items() if v not in ("", None))
        lines = [f"Trigger: {self.description}", f"Watches: {self.source} ({cond})", f"Then: {what}",
                 f"Checks every {_human(self.every_s)}; at most one run per {_human(self.cooldown_s)}",
                 f"Output: {self.output}", f"Read by: {self.read_by}"]
        if self.source in ("file_new", "email_from", "web_search_new"):
            lines.append("What exists now is noted first; only new items after that fire.")
        if self.source == "email_from":
            lines.append("The action gets the message id only (sender and subject too if allowed by "
                         "gmail.header_class); the email text itself is never passed on.")
        if self.source in ("web_price", "web_search_new"):
            lines.append("Uses Tavily credits; a daily limit applies (config/proactive.yaml, triggers).")
        lines.append("Runs unattended: only read-only work and new files (T0/T1); anything else waits for approval.")
        return "\n".join(lines)


def _human(seconds: int) -> str:
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


# ---------------------------------------------------------------- validation


def resolve_folder(raw: str, home: Path, roots: list[Path]) -> Path:
    """A folder inside the allowed file roots. "workspace/inbox" and "inbox" both mean
    <home>/workspace/inbox when workspace is the first root."""
    from jarvis.tools.files import is_secret_path

    p = Path(raw).expanduser()
    candidates = [p] if p.is_absolute() else [home / p, roots[0] / p] if roots else [home / p]
    resolved_roots = [r.expanduser().resolve() for r in roots]
    for c in candidates:
        path = c.resolve()
        if is_secret_path(path):
            raise TriggerInvalid(f"{raw} is a protected location")
        if any(path == r or path.is_relative_to(r) for r in resolved_roots):
            return path
    allowed = ", ".join(str(r) for r in roots) or "(none)"
    raise TriggerInvalid(f"{raw} is outside the folders Jarvis may read ({allowed}). "
                         "More folders can be added in config/local.yaml (tools.files.allowed).")


AMAZON_FLIPKART = ("Not saved: {host} prices may not be collected automatically (its terms forbid it). "
                   "Use the same product's page on an official store (Croma, Reliance Digital, Vijay Sales or the "
                   "brand's India store) instead.")


def check_price_url(url: str) -> None:
    from jarvis.agents.sources import classify

    tier = classify(url)
    if tier.kind == "user_check":
        raise TriggerInvalid(AMAZON_FLIPKART.format(host=tier.match))
    if tier.kind != "store":
        raise TriggerInvalid(f"Not saved: {tier.match} is not an official store page (tier {tier.tier}, "
                             f"{tier.describe}). Price triggers watch store pages only (config/sources.yaml, store).")


def validate(draft: TriggerDraft, home: Path | None = None, roots: list[Path] | None = None) -> TriggerDraft:
    if draft.source not in SOURCES:
        raise TriggerInvalid(f"source must be one of {', '.join(SOURCES)}")
    if draft.action not in ACTIONS:
        raise TriggerInvalid(f"action must be one of {', '.join(ACTIONS)}")
    if draft.output not in OUTPUTS:
        raise TriggerInvalid(f"output must be one of {', '.join(OUTPUTS)}")
    if draft.action in ("skill", "agent") and not draft.target:
        raise TriggerInvalid(f"a {draft.action} action needs a {draft.action} name")
    if draft.action == "prompt" and not draft.input.strip():
        raise TriggerInvalid("say what Jarvis should do when it fires")
    c = draft.condition
    if draft.source == "file_new":
        if not c.get("folder"):
            raise TriggerInvalid("which folder should Jarvis watch?")
        if home is not None and roots is not None:
            resolve_folder(str(c["folder"]), home, roots)
    elif draft.source == "web_price":
        if not c.get("url"):
            raise TriggerInvalid("give the store page link of the product")
        check_price_url(str(c["url"]))
        try:
            if float(c.get("below") or 0) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise TriggerInvalid("give the price limit in rupees, e.g. 75000") from None
    elif draft.source == "email_from":
        if not (c.get("sender") or c.get("subject")):
            raise TriggerInvalid("give a sender (email address or name) or a subject word")
    elif draft.source == "calendar_soon":
        try:
            minutes = int(c.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if not 1 <= minutes <= 1440:
            raise TriggerInvalid("minutes before the event must be between 1 and 1440")
    elif draft.source == "web_search_new":
        if not str(c.get("query") or "").strip():
            raise TriggerInvalid("what should Jarvis search for?")
    if draft.every_s < 60:
        raise TriggerInvalid("check interval must be at least 1 minute")
    if draft.cooldown_s < 0:
        raise TriggerInvalid("cooldown cannot be negative")
    return draft


# ---------------------------------------------------------------- amounts


_AMOUNT = re.compile(r"(₹|\brs\.?|\binr)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k\b|thousand\b|hazar\b|हजार|lakh\b|lac\b|लाख)?",
                     re.IGNORECASE)


def parse_amount(text: str) -> float | None:
    """The price limit in a sentence: an amount with Rs/₹ wins, else the largest number."""
    best: tuple[int, float] | None = None
    for m in _AMOUNT.finditer(text):
        try:
            value = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(3) or "").lower()
        if unit in ("k", "thousand", "hazar", "हजार"):
            value *= 1000
        elif unit in ("lakh", "lac", "लाख"):
            value *= 100000
        score = (1 if m.group(1) else 0, value)
        if value > 0 and (best is None or score > best):  # type: ignore[operator]
            best = score  # type: ignore[assignment]
    return best[1] if best else None


# ---------------------------------------------------------------- parser


@dataclass
class _Match:
    source: str
    condition: dict[str, Any]
    end: int                         # where the condition ends in the text (English word order)
    description: str
    extra_spans: list[tuple[int, int]] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_FILE_WORD = re.compile(r"\b(files?|documents?|docs?)\b|फाइल|फाईल", re.IGNORECASE)
_NEWISH = re.compile(r"\b(new|navin|nava|navi|arrives?|added|aali|ali|aaya|changed?|modified|saved|lands?|appears?|"
                     r"comes?)\b|नवीन|आली", re.IGNORECASE)
_FOLDER_EN = re.compile(r"\b(?:in|into|to|inside|under)\s+(?:the\s+|my\s+)?(?:folder\s+)?([^\s,;]+)", re.IGNORECASE)
_FOLDER_MR = re.compile(r"([^\s,;]+)\s+(?:folder\s+)?(?:madhe|madhye|mdhe|मध्ये|मधे)", re.IGNORECASE)
_GLOB = re.compile(r"(\*\.[A-Za-z0-9]+)")


def _file(text: str) -> _Match | None:
    fw = _FILE_WORD.search(text)
    if not fw or not _NEWISH.search(text):
        return None
    m = _FOLDER_EN.search(text, fw.end()) or _FOLDER_MR.search(text)
    if not m:
        raise TriggerParseError("Which folder should Jarvis watch? e.g. 'when a new file arrives in workspace/inbox "
                                "summarize it'")
    folder = m.group(1).strip("'\"").rstrip(".")
    glob = "*"
    g = _GLOB.search(text)
    if g:
        glob = g.group(1)
    else:
        before = text[: fw.start()].split()
        if before and before[-1].lower() in _EXT_WORDS:
            glob = _EXT_WORDS[before[-1].lower()]
    desc = f"new or changed file in {folder}" + (f" ({glob})" if glob != "*" else "")
    return _Match("file_new", {"folder": folder, "glob": glob}, max(m.end(), fw.end()), desc)


_EMAIL_WORD = re.compile(r"\b(e-?mails?|mails?|gmail)\b|ईमेल|मेल", re.IGNORECASE)
_FROM_EN = re.compile(r"\bfrom\s+([^\s,;]+)", re.IGNORECASE)
_FROM_MR = re.compile(r"([^\s,;]+)\s+(?:kadun|kadoon|kaDun|कडून)", re.IGNORECASE)
_SUBJECT = re.compile(r"\bsubject\s+(?:contains\s+|with\s+|has\s+|word\s+)?(?:\"([^\"]+)\"|'([^']+)'|([^\s,;]+))",
                      re.IGNORECASE)
_SUBJECT_WITH = re.compile(r"\bwith\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s,;]+))\s+in\s+the\s+subject", re.IGNORECASE)


def _email(text: str) -> _Match | None:
    if not _EMAIL_WORD.search(text):
        return None
    sender, end = "", 0
    addr = EMAIL_RE.search(text)
    if addr:
        sender, end = addr.group(0).rstrip("."), addr.end()
    else:
        m = _FROM_EN.search(text) or _FROM_MR.search(text)
        if m and m.group(1).lower() not in ("me", "the", "a"):
            sender, end = m.group(1).strip("'\""), m.end()
    subject = ""
    s = _SUBJECT.search(text) or _SUBJECT_WITH.search(text)
    if s:
        subject = next(g for g in s.groups() if g)
        end = max(end, s.end())
    if not sender and not subject:
        raise TriggerParseError("From whom? e.g. 'when I get an email from boss@example.com tell me', or "
                                "'email with subject invoice'.")
    desc = "new email" + (f" from {sender}" if sender else "") + (f" with '{subject}' in the subject" if subject else "")
    return _Match("email_from", {"sender": sender, "subject": subject}, end, desc)


_PRICE_WORD = re.compile(r"\b(price|prices|kimmat|kimat|kimmath|rate|cost|dam|daam)\b|किंमत|किमत", re.IGNORECASE)
_BELOW = re.compile(r"\b(below|under|less than|lower than|drops?|falls?|goes down|khali|khaali|kami)\b|खाली|कमी",
                    re.IGNORECASE)
_PRODUCT_EN = re.compile(r"\bprice of (?:the |my |a )?(.+?)\s+(?:drops?|falls?|goes|is|gets|comes)\b", re.IGNORECASE)
_PRODUCT_MR = re.compile(r"(?:\bjar\s+|जर\s+|^)(.+?)\s+(?:chi|chya|chee|ची|च्या)\s+(?:kimmat|kimat|किंमत|किमत)",
                         re.IGNORECASE)


def _price(text: str, url: str) -> _Match | None:
    if not (_PRICE_WORD.search(text) and _BELOW.search(text)):
        return None
    if not url:
        raise TriggerParseError("Give the store page link of the product, e.g. a croma.com or "
                                "reliancedigital.in product page.")
    amount = parse_amount(text)
    if not amount:
        raise TriggerParseError("Below what price? e.g. 'below 75000'.")
    product = ""
    p = _PRODUCT_EN.search(text) or _PRODUCT_MR.search(text)
    if p:
        product = p.group(1).strip()
    host = re.sub(r"^www\.", "", (re.match(r"https?://([^/]+)", url) or [None, url])[1])  # type: ignore[index]
    nums = list(_AMOUNT.finditer(text))
    end = max((m.end() for m in nums if m.group(2)), default=0)
    desc = f"price of {product or 'the product'} below Rs {amount:,.0f} at {host}"
    return _Match("web_price", {"url": url, "below": amount, "product": product}, end, desc)


_EVENT_WORD = re.compile(r"\b(meetings?|events?|calendar|appointments?|call)\b|मीटिंग|कार्यक्रम|भेट", re.IGNORECASE)
_MINUTES = re.compile(r"(\d{1,4})\s*(?:min|mins|minutes?|minit|minita|मिनिट|मिनिटे)\b", re.IGNORECASE)
_HOURS = re.compile(r"(\d{1,2})\s*(?:h|hr|hrs|hours?|tas|taas|तास)\b", re.IGNORECASE)
_SOONISH = re.compile(r"\b(before|starts?|starting|within|soon|adhi|aadhi|aagodar)\b|आधी", re.IGNORECASE)
_TITLED = re.compile(r"\b(?:titled|called|named)\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s,;]+))", re.IGNORECASE)


def _calendar(text: str) -> _Match | None:
    if not (_EVENT_WORD.search(text) and _SOONISH.search(text)):
        return None
    m = _MINUTES.search(text)
    minutes = int(m.group(1)) if m else 0
    end = m.end() if m else 0
    if not m:
        h = _HOURS.search(text)
        if not h:
            return None
        minutes, end = int(h.group(1)) * 60, h.end()
    title = ""
    t = _TITLED.search(text)
    if t:
        title = next(g for g in t.groups() if g)
    ev = _EVENT_WORD.search(text)
    end = max(end, ev.end() if ev else 0, t.end() if t else 0)
    desc = f"calendar event starting within {minutes} min" + (f" (title has '{title}')" if title else "")
    return _Match("calendar_soon", {"minutes": minutes, "title": title}, end, desc)


_SEARCH_WORD = re.compile(r"\b(new (?:search )?results?|search results?|news|new articles?|new posts?|batmi|baatmi|"
                          r"batmya)\b|बातमी|बातम्या", re.IGNORECASE)
_QUOTED = re.compile(r"\"([^\"]{2,})\"|'([^']{2,})'|“([^”]{2,})”")
_QUERY_EN = re.compile(r"\b(?:for|about|on)\s+(.+?)(?=,|;|\s+(?:then|and tell|tell|notify|let me|alert)\b|$)",
                       re.IGNORECASE)
_QUERY_MR = re.compile(r"(?:\bjar\s+|जर\s+|^)(.+?)\s+(?:baddal|badal|vishayi|बद्दल|विषयी)", re.IGNORECASE)


def _search(text: str) -> _Match | None:
    w = _SEARCH_WORD.search(text)
    if not w:
        return None
    q = _QUOTED.search(text)
    if q:
        query, end = next(g for g in q.groups() if g), q.end()
    else:
        m = _QUERY_EN.search(text, w.end()) or _QUERY_MR.search(text)
        if not m:
            raise TriggerParseError("Search for what? Put it in quotes, e.g. new results for 'new laptop launch India'.")
        query, end = m.group(1).strip(" .'\""), m.end()
    topic = "news" if re.search(r"\bnews\b|batmi|बातमी", text, re.IGNORECASE) else "general"
    return _Match("web_search_new", {"query": query, "topic": topic}, max(end, w.end()), f"new results for '{query}'")


def _action(text: str, match: _Match) -> tuple[str, str]:
    """(action kind, input). Marathi: the action follows 'tar'. English: the action follows
    the condition, or comes first ('tell me when ...')."""
    rest = ""
    mr = re.search(r"\s(?:tar|तर)\s+(.+)$", text, re.IGNORECASE)
    if mr:
        rest = mr.group(1)
    else:
        cond = _COND_START.search(text)
        if cond and cond.start() > 0:
            rest = text[: cond.start()]               # "tell me when ..." / "summarize it when ..."
        else:
            rest = text[match.end:]
    rest = URL_RE.sub(" ", rest)
    rest = _clean(rest).strip(" ,;:-")
    for _ in range(3):
        rest = _FILLER.sub("", rest).strip(" ,;:-")
    if not rest or _NOTIFY.search(rest):
        return "notify", ""
    return "prompt", rest


def parse_trigger(text: str, defaults: dict[str, Any] | None = None) -> TriggerDraft:
    """Raises TriggerParseError with a question when the text is not clear enough."""
    defaults = defaults or {}
    raw = _clean(text)
    if not raw:
        raise TriggerParseError("Say what to watch and what to do, e.g. 'when a new file arrives in workspace/inbox "
                                "summarize it'.")
    urls = URL_RE.findall(raw)
    url = urls[0].rstrip(".,;") if urls else ""
    no_url = _clean(URL_RE.sub(" ", raw)) if url else raw
    match = None
    # Order matters: a price sentence may mention "laptop"; an email sentence may mention "file".
    for fn in (lambda t: _price(t, url), _email, _calendar, _file, _search):
        match = fn(no_url)
        if match:
            break
    if match is None:
        raise TriggerParseError(
            "I could not tell what to watch. I understand: a new file in a folder, an email from someone, a store "
            "price below a limit (with the store link), a calendar event starting soon, or new web results for a "
            "search.")
    kind, rest = _action(no_url, match)
    if defaults.get("action"):
        kind = defaults["action"]
        if kind in ("skill", "agent") and rest == "" and defaults.get("input"):
            rest = defaults["input"]
    every = defaults.get("every_s")
    cooldown = defaults.get("cooldown_s")
    draft = TriggerDraft(
        name=match.description[:60], source=match.source, condition=match.condition, action=kind,
        target=defaults.get("target", ""), input=defaults.get("input") or rest, output=defaults.get("output", "telegram"),
        every_s=int(every) if every else 300, cooldown_s=int(cooldown) if cooldown is not None else 600,
        description=match.description, read_by="rules")
    if draft.source == "web_price" and defaults.get("product"):
        draft.condition["product"] = defaults["product"]
    return draft
