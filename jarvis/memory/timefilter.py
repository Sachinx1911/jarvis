"""Time-aware retrieval: pull a date range out of a question (LongMemEval time-aware expansion).

Deterministic first. English, Devanagari Marathi and romanized Marathi:
- today / aaj / आज, yesterday / kal / काल, day before yesterday / parva / परवा
- last week / मागच्या आठवड्यात / gelya athavdyat, this week / ya athavdyat
- last month / gelya mahinyat / मागच्या महिन्यात, this month, last year / gelya varshi
- N days / weeks / months ago (3 divsapurvi, ३ दिवसांपूर्वी), last N days
- last Monday / somvari / सोमवारी (most recent past one)
- explicit dates: 2026-09-14, 14/09/2026 (day first), 14 September, Sept 14, सप्टेंबर
- recently / nuktach / नुकतंच / halli (last 14 days)

"kal" is yesterday in Marathi but tomorrow in Hindi; "parva" is both the day before
yesterday and the day after tomorrow in Marathi. Memory questions are about the past, so
both read as past, unless the sentence is in the future tense (udya, -nar verbs, "will").

The range is used to *boost* matching memories (by valid_from) and past messages (by ts)
before rank fusion, not to hard-filter them: a wrong guess then costs a little ranking,
never the answer.

model_range() is the optional model step for phrasings the rules miss. It goes through a
provider route chosen by the caller (the memory extractor route), never a direct call.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from jarvis.memory.translit import canonical_roman, is_devanagari, roman_forms, words as _tokens

RECENT_DAYS = 14


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date                      # inclusive
    label: str = ""
    words: frozenset[str] = field(default_factory=frozenset)   # query words that expressed the time

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def contains_iso(self, value: str) -> bool:
        """True when an ISO date or 'YYYY-MM-DD HH:MM:SS' string falls in the range."""
        try:
            return self.contains(date.fromisoformat(str(value)[:10]))
        except ValueError:
            return False

    def utc_bounds(self) -> tuple[str, str]:
        """Local-day bounds as UTC 'YYYY-MM-DD HH:MM:SS' strings (the messages.ts format)."""
        def utc(d: date, t: time) -> str:
            return datetime.combine(d, t).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return utc(self.start, time.min), utc(self.end, time(23, 59, 59))

    def contains_utc_ts(self, ts: str) -> bool:
        lo, hi = self.utc_bounds()
        return lo <= str(ts)[:19] <= hi


def _canon(words: set[str]) -> set[str]:
    return {canonical_roman(w) for w in words}


TODAY = _canon({"today", "aaj", "aj", "aajch", "ajch"})
YESTERDAY = _canon({"yesterday"})
KAL = _canon({"kal", "kaal", "kalch", "kaalch"})
PARVA = _canon({"parva", "parwa", "parava"})
TOMORROW = _canon({"tomorrow", "udya", "udyaa", "uddya"})
FUTURE = _canon({"will", "shall", "going", "hoil", "asel", "karen", "jain", "yeil", "udya", "tomorrow"})
LAST = _canon({"last", "previous", "past", "prior", "magchya", "magachya", "magil", "magcha", "magchi",
               "gelya", "gela", "geli", "pichle", "pichhle", "pichhla", "pichla"})
THIS = _canon({"this", "current", "ya", "hya", "chalu"})
WEEK = _canon({"week", "weeks", "hafta", "hapta", "athavda", "athavde"})
WEEK_STEMS = ("athav", "athvad")
MONTH = _canon({"month", "months", "mahina", "mahine"})
MONTH_STEMS = ("mahin",)
YEAR = _canon({"year", "years", "varsh", "varsha", "sal", "saal"})
YEAR_STEMS = ("varsh",)
DAY = _canon({"day", "days", "din", "dinon"})
DAY_STEMS = ("divas", "divs")
AGO = _canon({"ago", "before", "back", "purvi", "agodar", "pahile", "pehle"})
AGO_STEMS = ("purv",)
RECENT = _canon({"recently", "lately", "nuktach", "nuktacha", "halli", "hallich", "alikade", "alikdech"})
RECENT_STEMS = ("nukt", "nukat")
DAY_BEFORE = ("day", "before", "yesterday")

_WEEKDAYS = [
    ("monday", "somvar"), ("tuesday", "mangalvar"), ("wednesday", "budhvar"), ("thursday", "guruvar"),
    ("friday", "shukravar"), ("saturday", "shanivar"), ("sunday", "ravivar"),
]
_MONTHS: dict[int, set[str]] = {
    1: {"january", "jan", "janevari", "janvari"},
    2: {"february", "feb", "februari", "februvari", "febravari", "phebruvari"},
    3: {"march", "mar"},
    4: {"april", "apr", "epril", "epril"},
    5: {"may", "me"},
    6: {"june", "jun"},
    7: {"july", "jul", "julai"},
    8: {"august", "aug", "ogast", "agast", "ogust"},
    9: {"september", "sep", "sept", "saptembar", "septembar", "saptenbar"},
    10: {"october", "oct", "oktobar", "oktober", "aktobar"},
    11: {"november", "nov", "novembar", "novhembar", "novhenbar"},
    12: {"december", "dec", "disembar", "disenbar", "dicembar"},
}
_MONTH_FORMS = {canonical_roman(f): m for m, forms in _MONTHS.items() for f in forms}
_AMBIGUOUS_MONTHS = _canon({"may", "me", "mar", "jan"})   # common words too: need a number or a marker
_MONTH_CONTEXT = _canon({"in", "during", "madhe", "madhye", "last", "this", "of"}) | LAST
IN_AFTER = _canon({"madhe", "madhye", "mde", "madhi", "la", "var"})
_NUMBER_WORDS = {
    "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "ek": 1, "don": 2, "doan": 2, "tin": 3, "teen": 3, "char": 4, "pach": 5, "panch": 5,
    "few": 3, "couple": 2,
}
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b")
_ORD = re.compile(r"^(\d{1,2})(st|nd|rd|th|la|tarkhela|tarikhela)?$")


@dataclass
class _Tok:
    raw: str
    keys: set[str]
    num: int | None


def _tokenize(text: str) -> list[_Tok]:
    out = []
    for raw in _tokens(text):
        if is_devanagari(raw):
            keys = set(roman_forms(raw))
            digits = raw.translate({0x0966 + i: str(i) for i in range(10)})
            num = int(digits) if digits.isdigit() else None
        else:
            keys = {canonical_roman(raw), raw}
            m = _ORD.match(raw)
            num = int(m.group(1)) if m else _NUMBER_WORDS.get(raw)
        out.append(_Tok(raw, keys, num))
    return out


def _is(tok: _Tok, vocab: set[str], stems: tuple[str, ...] = ()) -> bool:
    return bool(tok.keys & vocab) or any(k.startswith(s) for k in tok.keys for s in stems)


def _day_number(tok: _Tok) -> bool:
    """A written day of the month (digits, "14th", "१४"), not a number word like "a"."""
    return tok.num is not None and 1 <= tok.num <= 31 and (tok.raw[:1].isdigit() or is_devanagari(tok.raw))


def _month_of(tok: _Tok) -> int | None:
    for k in tok.keys:
        if k in _MONTH_FORMS:
            return _MONTH_FORMS[k]
        for form, m in _MONTH_FORMS.items():
            if len(form) >= 5 and k.startswith(form):
                return m
    return None


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(d: date, months: int) -> tuple[int, int]:
    idx = d.year * 12 + (d.month - 1) + months
    return idx // 12, idx % 12 + 1


def _past_date(today: date, month: int, day: int, year: int | None) -> date | None:
    try:
        if year is not None:
            return date(year if year > 100 else 2000 + year, month, day)
        d = date(today.year, month, day)
        return d if d <= today else date(today.year - 1, month, day)
    except ValueError:
        return None


def _make(start: date, end: date, label: str, toks: list[_Tok], used: set[int]) -> DateRange:
    return DateRange(start, end, label, frozenset(toks[i].raw for i in used))


def extract_range(text: str, today: date) -> DateRange | None:
    """The date range a question refers to, or None when it names no time."""
    if not text.strip():
        return None
    low = text.lower()
    toks = _tokenize(low)
    n = len(toks)
    # Future tense: "will", udya, or a Marathi -nar verb (karnar, yenar, janar).
    future = any(_is(t, FUTURE) or any(len(k) > 4 and k.endswith("nar") for k in t.keys) for t in toks)

    # 1. explicit numeric dates
    m = _ISO.search(low)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            used = {i for i, t in enumerate(toks) if t.raw in m.group(0).split("-")}
            return _make(d, d, "date", toks, used)
        except ValueError:
            pass
    m = _DMY.search(low)
    if m:
        d = _past_date(today, int(m.group(2)), int(m.group(1)), int(m.group(3)))
        if d:
            used = {i for i, t in enumerate(toks) if t.raw in re.split(r"[/.]", m.group(0))}
            return _make(d, d, "date", toks, used)

    # 2. day + month name, month name + day, or a month on its own
    for i, t in enumerate(toks):
        month = _month_of(t)
        if month is None:
            continue
        prev_num = toks[i - 1].num if i > 0 and _day_number(toks[i - 1]) else None
        next_num = toks[i + 1].num if i + 1 < n and _day_number(toks[i + 1]) else None
        if t.keys & _AMBIGUOUS_MONTHS:
            next_num = None   # "give me 5 ideas" is not 5 May; "5 May" / "5 मे" still is
        year = None
        year_idx = None
        for j in (i + 1, i + 2):
            if j < n and re.fullmatch(r"\d{4}", toks[j].raw):
                year, year_idx = int(toks[j].raw), j
        day = prev_num or next_num
        if day:
            d = _past_date(today, month, day, year)
            if d:
                used = {i, i - 1 if prev_num else i + 1} | ({year_idx} if year_idx is not None else set())
                return _make(d, d, "date", toks, used)
        ambiguous = bool(t.keys & _AMBIGUOUS_MONTHS)
        if ambiguous and not (i > 0 and _is(toks[i - 1], _MONTH_CONTEXT)) and year is None:
            continue
        y = year if year is not None else (today.year if month <= today.month else today.year - 1)
        s, e = _month_range(y, month)
        used = {i} | ({year_idx} if year_idx is not None else set())
        if i > 0 and _is(toks[i - 1], _MONTH_CONTEXT):
            used.add(i - 1)
        if i + 1 < n and _is(toks[i + 1], IN_AFTER):
            used.add(i + 1)
        return _make(s, e, "month", toks, used)

    # 3. N days / weeks / months ago, last N days
    for i, t in enumerate(toks):
        if t.num is None or i + 1 >= n:
            continue
        unit_tok = toks[i + 1]
        if _is(unit_tok, DAY, DAY_STEMS):
            days = t.num
        elif _is(unit_tok, WEEK, WEEK_STEMS):
            days = 7 * t.num
        elif _is(unit_tok, MONTH, MONTH_STEMS):
            days = 30 * t.num
        else:
            continue
        used = {i, i + 1}
        ago = any(s in k for k in unit_tok.keys for s in AGO_STEMS) or (i + 2 < n and _is(toks[i + 2], AGO, AGO_STEMS))
        if ago:
            if i + 2 < n and _is(toks[i + 2], AGO, AGO_STEMS):
                used.add(i + 2)
            d = today - timedelta(days=days)
            slack = 0 if days < 7 else 3
            return _make(d - timedelta(days=slack), d + timedelta(days=slack), "ago", toks, used)
        if i > 0 and _is(toks[i - 1], LAST):
            used.add(i - 1)
            return _make(today - timedelta(days=days), today, "last_n", toks, used)

    # 4. last / this week, month, year
    for i, t in enumerate(toks):
        if i + 1 >= n:
            break
        nxt = toks[i + 1]
        is_last, is_this = _is(t, LAST), _is(t, THIS)
        if not (is_last or is_this):
            continue
        used = {i, i + 1}
        if _is(nxt, WEEK, WEEK_STEMS):
            monday = today - timedelta(days=today.weekday())
            if is_last:
                return _make(monday - timedelta(days=7), monday - timedelta(days=1), "last_week", toks, used)
            return _make(monday, today, "this_week", toks, used)
        if _is(nxt, MONTH, MONTH_STEMS):
            if is_last:
                y, mth = _shift_month(today, -1)
                s, e = _month_range(y, mth)
                return _make(s, e, "last_month", toks, used)
            return _make(today.replace(day=1), today, "this_month", toks, used)
        if _is(nxt, YEAR, YEAR_STEMS):
            if is_last:
                return _make(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last_year", toks, used)
            return _make(date(today.year, 1, 1), today, "this_year", toks, used)
        if is_last:
            wd = _weekday(nxt)
            if wd is not None:
                d = _last_weekday(today, wd)
                return _make(d, d, "weekday", toks, used)

    # 5. single relative days
    for i in range(n - 2):
        if [toks[i + k].raw for k in range(3)] == list(DAY_BEFORE):
            d = today - timedelta(days=2)
            return _make(d, d, "day_before_yesterday", toks, {i, i + 1, i + 2})
    for i, t in enumerate(toks):
        if _is(t, PARVA):
            d = today + timedelta(days=2) if future else today - timedelta(days=2)
            return _make(d, d, "parva", toks, {i})
        if _is(t, YESTERDAY):
            d = today - timedelta(days=1)
            return _make(d, d, "yesterday", toks, {i})
        if _is(t, KAL):
            d = today + timedelta(days=1) if future else today - timedelta(days=1)
            return _make(d, d, "kal_future" if future else "kal", toks, {i})
        if _is(t, TODAY):
            return _make(today, today, "today", toks, {i})
        if _is(t, RECENT, RECENT_STEMS):
            return _make(today - timedelta(days=RECENT_DAYS), today, "recent", toks, {i})

    # 6. a weekday on its own: the most recent past one
    for i, t in enumerate(toks):
        wd = _weekday(t)
        if wd is not None:
            d = _last_weekday(today, wd)
            return _make(d, d, "weekday", toks, {i})
    return None


def _weekday(tok: _Tok) -> int | None:
    for idx, (en, mr) in enumerate(_WEEKDAYS):
        if any(k == canonical_roman(en) or k.startswith(mr) for k in tok.keys):
            return idx
    return None


def _last_weekday(today: date, wd: int) -> date:
    back = (today.weekday() - wd) % 7 or 7
    return today - timedelta(days=back)


# ---- optional model step ----

TIME_CUES = _canon({"when", "date", "ago", "since", "before", "after", "kevha", "keva", "kadhi", "tarikh",
                    "tarkh", "pasun", "nantar", "adhi", "purvi"})
MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "has_time": {"type": "boolean"},
        "start": {"type": "string"},
        "end": {"type": "string"},
    },
    "required": ["has_time", "start", "end"],
    "additionalProperties": False,
}
MODEL_PROMPT = (
    "You read one question a user asks their assistant about the past. If it refers to a time "
    "period, return its start and end dates (YYYY-MM-DD, inclusive) relative to today's date. "
    "If it names no time period, return has_time false and empty strings. Return JSON only."
)


def has_time_cue(text: str) -> bool:
    return any(t.keys & TIME_CUES for t in _tokenize(text.lower()))


def model_range(text: str, today: date, provider: Any, decision: Any, audit: Any = None) -> DateRange | None:
    """Rules first; if they find nothing and the question has a time cue, ask the model
    through the caller's route (e.g. memory_extractor). Any failure means no range."""
    rng = extract_range(text, today)
    if rng or provider is None or decision is None or not has_time_cue(text):
        return rng
    from jarvis.providers.base import LLMRequest, Message, ProviderError

    req = LLMRequest(
        route=decision.route, model=decision.model, system=MODEL_PROMPT,
        messages=[Message.text("user", f"Today is {today.isoformat()}.\nQuestion: {text}")],
        reasoning=decision.effort, response_schema=MODEL_SCHEMA, privacy_classes=frozenset({"P1"}),
    )
    try:
        res = provider.structured(req, MODEL_SCHEMA)
    except (ProviderError, NotImplementedError) as e:
        if audit:
            audit.write("timefilter_model_error", route=decision.route, detail=str(e))
        return None
    data = res.data if res.valid else None
    if not isinstance(data, dict) or not data.get("has_time"):
        return None
    try:
        start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if end < start or (end - start).days > 3660:
        return None
    return DateRange(start, end, "model")
