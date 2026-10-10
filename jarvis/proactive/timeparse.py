"""Deterministic time phrases: English, romanized Marathi and a few Devanagari words.

Used for schedules ("every Monday at 9", "roj sakali 8 la") and reminders ("in 10
minutes", "udya sakali 9 la"). Rules first because they are free, instant and exact;
only text these rules cannot read goes to a model (see schedule_parse.py). When the
rules are unsure they return None rather than guess.

Cron output always uses day NAMES (mon, tue ...), never numbers: APScheduler 3's
from_crontab counts 0 as Monday, standard cron counts 0 as Sunday, and names avoid the
difference entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_FULL = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_DAY_STEMS = {
    0: ("monday", "mon", "somvar", "somwar", "सोमवार"),
    1: ("tuesday", "tue", "tues", "mangalvar", "mangalwar", "मंगळवार"),
    2: ("wednesday", "wed", "budhvar", "budhwar", "बुधवार"),
    3: ("thursday", "thu", "thur", "thurs", "guruvar", "guruwar", "गुरुवार"),
    4: ("friday", "fri", "shukravar", "shukrawar", "शुक्रवार"),
    5: ("saturday", "shanivar", "shaniwar", "शनिवार"),
    6: ("sunday", "ravivar", "raviwar", "रविवार"),
}
DAY_WORDS: dict[str, int] = {}
for _d, _stems in _DAY_STEMS.items():
    for _s in _stems:
        DAY_WORDS[_s] = _d
        if len(_s) > 4:
            DAY_WORDS[_s + "s"] = _d  # mondays
            DAY_WORDS[_s + "i"] = _d  # somvari (on Monday)
            DAY_WORDS[_s + "ी"] = _d  # सोमवारी
# Plural / "-i" forms already say "every" on their own.
_PLURAL_DAYS = {w for w in DAY_WORDS if w.endswith("s") and w[:-1] in DAY_WORDS and len(w) > 5}

EVERY = {"every", "each", "dar", "pratyek", "har", "दर", "प्रत्येक"}
AT = {"at", "@", "by"}
ON = {"on"}
AM = {"am"}
PM = {"pm"}
# Marathi "at 8": "8 la", "8 vajta"; Hindi-ish "8 baje" is common in romanized chat too.
AT_SUFFIX = {"la", "laa", "vajta", "vajata", "wajta", "vaajta", "vajta.", "baje", "o'clock", "oclock", "वाजता", "ला"}

PERIODS = {
    "morning": "morning", "sakali": "morning", "sakaali": "morning", "sakal": "morning", "सकाळी": "morning",
    "afternoon": "afternoon", "dupari": "afternoon", "dupaari": "afternoon", "दुपारी": "afternoon",
    "evening": "evening", "sandhyakali": "evening", "sandhyakaali": "evening", "sandhyakal": "evening",
    "sayankali": "evening", "संध्याकाळी": "evening", "सायंकाळी": "evening",
    "night": "night", "tonight": "night", "ratri": "night", "raatri": "night", "रात्री": "night",
}
PERIOD_DEFAULT_HOUR = {"morning": 9, "afternoon": 14, "evening": 18, "night": 21}

DAILY = {"daily", "everyday", "roj", "roz", "rojch", "daroj", "dररोज", "दररोज", "रोज", "nightly"}
DAY_UNIT = {"day", "days", "divashi", "divshi", "din", "दिवशी"}
WEEKDAY_SET = {"weekday", "weekdays"}
WEEKEND_SET = {"weekend", "weekends"}
MONTH_UNIT = {"month", "months", "mahina", "mahinyala", "mahinyachya", "महिन्याला"}
MONTHLY = {"monthly"}
HOURLY = {"hourly"}

MINUTE_UNITS = {"minute", "minutes", "min", "mins", "minit", "minita", "minitani", "minitanni", "minutani",
                "minutanni", "mintani", "minitane", "मिनिटांनी", "मिनिटे", "मिनिट"}
HOUR_UNITS = {"hour", "hours", "hr", "hrs", "tas", "taas", "tasala", "taasala", "tasani", "tasanni",
              "taasani", "tasane", "तास", "तासाने", "तासांनी", "तासाला"}
DAY_UNITS = {"day", "days", "divsani", "divasani", "divasanni", "दिवसांनी"}
AFTER_SUFFIX = {"nantar", "ne", "नंतर"}  # "10 minute nantar" = after 10 minutes
IN_WORDS = {"in", "after"}

TODAY = {"today", "aaj", "aj", "आज"}
TOMORROW = {"tomorrow", "tmrw", "udya", "udyaa", "uddya", "उद्या"}
DAY_AFTER = {"parva", "parwa", "परवा"}
CONNECT = {"and", "&", "ani", "आणि", ","}
ORDINAL = {"st", "nd", "rd", "th", "tarkhela", "tarikhela", "tarkhes", "तारखेला"}

_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[:.]\d{2}|\d+|[^\s\d,;!?।]+|,")
_HHMM = re.compile(r"^(\d{1,2})[:.](\d{2})$")


@dataclass
class Token:
    norm: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    out = []
    for m in _TOKEN.finditer(text):
        raw = m.group(0)
        norm = raw.lower()
        if norm in ("a.m.", "a.m", "p.m.", "p.m"):
            norm = norm.replace(".", "")
        elif not _HHMM.match(norm):
            norm = norm.rstrip(".:")
        if norm:
            out.append(Token(norm, m.start(), m.end()))
    return out


@dataclass
class TimeOfDay:
    hour: int
    minute: int
    used: set[int] = field(default_factory=set)
    explicit: bool = True  # False when only a period word ("tomorrow evening") gave the time


def _apply_period(hour: int, ampm: str | None, period: str | None) -> int | None:
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif ampm is None and period and hour <= 12:
        if period in ("afternoon", "evening") and hour < 12:
            hour += 12
        elif period == "night":
            hour = 0 if hour == 12 else hour + 12 if hour >= 6 else hour
    if hour == 24:
        hour = 0
    return hour if 0 <= hour <= 23 else None


def find_period(tokens: list[Token], used: set[int]) -> tuple[str | None, int | None]:
    for i, t in enumerate(tokens):
        if i not in used and t.norm in PERIODS:
            return PERIODS[t.norm], i
    return None, None


def find_time(tokens: list[Token], used: set[int]) -> TimeOfDay | None:
    """A clock time: "9:30", "9am", "at 9", "8 la", "sakali 8", "noon"."""
    period, period_idx = find_period(tokens, used)
    for i, t in enumerate(tokens):
        if i in used:
            continue
        nxt = tokens[i + 1].norm if i + 1 < len(tokens) else ""
        prev = tokens[i - 1].norm if i > 0 else ""
        idx: set[int] = {i}
        hour = minute = None
        if t.norm in ("noon", "midday"):
            hour, minute = 12, 0
        elif t.norm == "midnight":
            hour, minute = 0, 0
        elif m := _HHMM.match(t.norm):
            hour, minute = int(m.group(1)), int(m.group(2))
        elif t.norm.isdigit() and len(t.norm) <= 2:
            marked = nxt in AM | PM | AT_SUFFIX or prev in AT or (period_idx is not None and period_idx == i - 1)
            if not marked or (i + 1 < len(tokens) and nxt in MINUTE_UNITS | HOUR_UNITS | DAY_UNITS | ORDINAL):
                continue
            hour, minute = int(t.norm), 0
        else:
            continue
        ampm = None
        if nxt in AM | PM:
            ampm = "am" if nxt in AM else "pm"
            idx.add(i + 1)
            nxt2 = tokens[i + 2].norm if i + 2 < len(tokens) else ""
            if nxt2 in AT_SUFFIX:
                idx.add(i + 2)
        elif nxt in AT_SUFFIX:
            idx.add(i + 1)
        if prev in AT:
            idx.add(i - 1)
        if minute is None or minute > 59:
            continue
        h = _apply_period(hour, ampm, period)
        if h is None:
            continue
        if period_idx is not None:
            idx.add(period_idx)
        return TimeOfDay(h, minute, idx)
    if period is not None and period_idx is not None:
        return TimeOfDay(PERIOD_DEFAULT_HOUR[period], 0, {period_idx}, explicit=False)
    return None


def remainder(text: str, tokens: list[Token], used: set[int], edge_words: set[str] | None = None) -> str:
    """The text without the time phrase, e.g. the prompt or the reminder message."""
    keep = [i for i in range(len(tokens)) if i not in used]
    edge = edge_words if edge_words is not None else {"at", "on", "to", "in", "every", "each", "la", "dar",
                                                       "and", "ani", "from", "for", ","}
    while keep and tokens[keep[0]].norm in edge:
        keep.pop(0)
    while keep and tokens[keep[-1]].norm in edge:
        keep.pop()
    if not keep:
        return ""
    # Rebuild from the original text so spacing, case and punctuation stay as typed.
    pieces: list[str] = []
    for n, i in enumerate(keep):
        if n:
            prev = keep[n - 1]
            pieces.append(text[tokens[prev].end:tokens[i].start] if i == prev + 1 else " ")
        pieces.append(text[tokens[i].start:tokens[i].end])
    return re.sub(r"\s+", " ", "".join(pieces)).strip(" ,.;:-")


# ---------------------------------------------------------------- recurring


@dataclass
class Recurring:
    cron: str
    description: str
    rest: str  # what is left of the text: usually what to run


def _hm(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def _number_before(tokens: list[Token], i: int) -> int | None:
    if i > 0 and tokens[i - 1].norm.isdigit():
        return int(tokens[i - 1].norm)
    return None


def parse_recurring(text: str) -> Recurring | None:
    tokens = tokenize(text)
    norms = [t.norm for t in tokens]
    used: set[int] = set()
    has_every = False
    for i, n in enumerate(norms):
        if n in EVERY:
            has_every = True
            used.add(i)

    # Intervals: "every 30 minutes", "every 2 hours", "every hour", "hourly", "dar tasala".
    for i, n in enumerate(norms):
        if n in MINUTE_UNITS | HOUR_UNITS and (has_every or n in ("tasala", "taasala", "तासाला")):
            num = _number_before(tokens, i)
            if num is not None:
                used |= {i, i - 1}
            elif i > 0 and norms[i - 1] in ("half",) and n in HOUR_UNITS:
                num, n = 30, "minutes"
                used |= {i, i - 1}
                if i > 1 and norms[i - 2] in ("a", "an"):
                    used.add(i - 2)
            else:
                num = 1
                used.add(i)
            if n in MINUTE_UNITS:
                if not 1 <= num <= 59:
                    return None
                return Recurring(f"*/{num} * * * *", f"every {num} minutes", remainder(text, tokens, used))
            if not 1 <= num <= 23:
                return None
            if num == 1:
                return Recurring("0 * * * *", "every hour, on the hour", remainder(text, tokens, used))
            return Recurring(f"0 */{num} * * *", f"every {num} hours, on the hour", remainder(text, tokens, used))
        if n in HOURLY:
            used.add(i)
            return Recurring("0 * * * *", "every hour, on the hour", remainder(text, tokens, used))

    # Which days?
    days: list[int] = []
    kind = None
    plural_or_every = has_every
    for i, n in enumerate(norms):
        if n in DAY_WORDS:
            if DAY_WORDS[n] not in days:
                days.append(DAY_WORDS[n])
            used.add(i)
            if n in _PLURAL_DAYS or i > 0 and norms[i - 1] in ON:
                if n in _PLURAL_DAYS:
                    plural_or_every = True
                if i > 0 and norms[i - 1] in ON:
                    used.add(i - 1)
            if i + 1 < len(norms) and norms[i + 1] in CONNECT and i + 2 < len(norms) and norms[i + 2] in DAY_WORDS:
                used.add(i + 1)
        elif n in WEEKDAY_SET:
            kind = "weekdays"
            used.add(i)
            if i > 0 and norms[i - 1] in ON:
                used.add(i - 1)
        elif n in WEEKEND_SET:
            kind = "weekend"
            used.add(i)
            if i > 0 and norms[i - 1] in ON:
                used.add(i - 1)
        elif n in DAILY:
            kind = kind or "daily"
            used.add(i)
        elif n in DAY_UNIT and i > 0 and norms[i - 1] in EVERY:
            kind = kind or "daily"
            used.add(i)
        elif n in MONTHLY or (n in MONTH_UNIT and has_every):
            kind = "monthly"
            used.add(i)
    if days and kind is None:
        if not plural_or_every:
            return None  # "on Monday at 9" is a one-off, not a schedule
        kind = "weekly"
    if kind is None and has_every:
        # "every morning at 7", "every evening"
        period, pidx = find_period(tokens, used)
        if period is not None and pidx is not None and pidx > 0 and norms[pidx - 1] in EVERY:
            kind = "daily"
    if kind is None:
        return None

    dom = None
    if kind == "monthly":
        for i, n in enumerate(norms):
            if i in used or not n.isdigit():
                continue
            nxt = norms[i + 1] if i + 1 < len(norms) else ""
            prev = norms[i - 1] if i > 0 else ""
            if nxt in ORDINAL or (prev in ON | {"the"} and nxt not in AM | PM | AT_SUFFIX):
                dom = int(n)
                used.add(i)
                if nxt in ORDINAL:
                    used.add(i + 1)
                for back in (i - 1, i - 2):
                    if back >= 0 and norms[back] in ON | {"the"}:
                        used.add(back)
                break
        if dom is None or not 1 <= dom <= 31:
            return None

    tod = find_time(tokens, used)
    if tod is None:
        return None  # no time given: ask instead of guessing
    used |= tod.used
    h, m = tod.hour, tod.minute
    rest = remainder(text, tokens, used)
    if kind == "daily":
        return Recurring(f"{m} {h} * * *", f"every day at {_hm(h, m)}", rest)
    if kind == "weekdays":
        return Recurring(f"{m} {h} * * mon-fri", f"every weekday (Mon-Fri) at {_hm(h, m)}", rest)
    if kind == "weekend":
        return Recurring(f"{m} {h} * * sat,sun", f"every Saturday and Sunday at {_hm(h, m)}", rest)
    if kind == "monthly":
        return Recurring(f"{m} {h} {dom} * *", f"every month on day {dom} at {_hm(h, m)}", rest)
    days.sort()
    names = " and ".join(DAY_FULL[d] for d in days)
    return Recurring(f"{m} {h} * * {','.join(DAY_NAMES[d] for d in days)}", f"every {names} at {_hm(h, m)}", rest)


# ---------------------------------------------------------------- one-off


@dataclass
class OneOff:
    due: datetime
    rest: str


def parse_once(text: str, now: datetime) -> OneOff | None:
    """A single moment: "in 10 minutes", "tomorrow at 9", "udya sakali 8 la", "at 18:30",
    "on Friday at 5pm", "on 2026-10-12 at 9". `now` must be timezone-aware."""
    tokens = tokenize(text)
    norms = [t.norm for t in tokens]
    used: set[int] = set()

    # Relative: "in 10 minutes", "10 minitani", "2 tasani", "in an hour", "in half an hour".
    for i, n in enumerate(norms):
        unit = ("m" if n in MINUTE_UNITS else "h" if n in HOUR_UNITS else "d" if n in DAY_UNITS else None)
        if unit is None:
            continue
        num: float | None = None
        idx = {i}
        if i > 0 and norms[i - 1].isdigit():
            num = int(norms[i - 1])
            idx.add(i - 1)
        elif i > 0 and norms[i - 1] in ("a", "an", "one"):
            num = 1
            idx.add(i - 1)
            if i > 1 and norms[i - 2] == "half":
                num = 0.5
                idx.add(i - 2)
        elif i > 0 and norms[i - 1] in ("half", "ardhya", "अर्ध्या"):
            num = 0.5
            idx.add(i - 1)
        if num is None:
            continue
        start = min(idx)
        if start > 0 and norms[start - 1] in IN_WORDS:
            idx.add(start - 1)
        elif not (n.endswith(("ani", "anni", "ane", "ांनी", "ाने")) or
                  (i + 1 < len(norms) and norms[i + 1] in AFTER_SUFFIX)):
            continue  # "10 minutes" alone is not a moment
        if i + 1 < len(norms) and norms[i + 1] in AFTER_SUFFIX:
            idx.add(i + 1)
        delta = {"m": timedelta(minutes=num), "h": timedelta(hours=num), "d": timedelta(days=num)}[unit]
        if delta <= timedelta(0):
            return None
        used |= idx
        return OneOff(now + delta, remainder(text, tokens, used))

    # Day anchor.
    day: date | None = None
    weekday: int | None = None
    for i, n in enumerate(norms):
        if i in used:
            continue
        if n in TODAY:
            day = now.date()
        elif n in TOMORROW:
            day = now.date() + timedelta(days=1)
        elif n in DAY_AFTER or (n == "day" and norms[i + 1:i + 3] == ["after", "tomorrow"]):
            day = now.date() + timedelta(days=2)
            if n == "day":
                used |= {i + 1, i + 2}
                if i > 0 and norms[i - 1] == "the":
                    used.add(i - 1)
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", n):
            try:
                day = date.fromisoformat(n)
            except ValueError:
                return None
        elif n in DAY_WORDS and n not in _PLURAL_DAYS:
            weekday = DAY_WORDS[n]
        else:
            continue
        used.add(i)
        if i > 0 and norms[i - 1] in ON:
            used.add(i - 1)
        break

    tod = find_time(tokens, used)
    if tod is None and day is None and weekday is None:
        return None
    if tod is not None:
        used |= tod.used
        h, m = tod.hour, tod.minute
    else:
        h, m = 9, 0  # "tomorrow" with no time: 9 in the morning
    tz = now.tzinfo
    if weekday is not None:
        ahead = (weekday - now.weekday()) % 7
        day = now.date() + timedelta(days=ahead)
        if ahead == 0 and datetime(day.year, day.month, day.day, h, m, tzinfo=tz) <= now:
            day += timedelta(days=7)
    if day is None:
        day = now.date()
        if datetime(day.year, day.month, day.day, h, m, tzinfo=tz) <= now:
            day += timedelta(days=1)  # "at 9" when 9 has passed means tomorrow
    due = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
    if due <= now:
        return None  # in the past: ask instead of guessing
    return OneOff(due, remainder(text, tokens, used))
