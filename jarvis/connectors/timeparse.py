"""Deterministic natural time parsing for events: "tomorrow at 11", "Monday 5 pm", "udya 11 la".

Why deterministic: the time of an event must not depend on a model's guess. The model
calls the parse_time tool, shows Sachin the exact result, and passes the ISO times to
calendar_create_event, whose approval prompt shows them again.

Understands English and basic romanized (and Devanagari) Marathi:
  days     today/aaj, tomorrow/udya, day after tomorrow/parva, weekdays (monday/somvar ...),
           "next <weekday>"/"pudhcha somvar", "in 2 hours", 12 Oct, Oct 12, 12/10 (day/month), 2026-10-12
  times    11, 11:30, 11.30, 5 pm, 17:00, noon/dupari 12, midnight, "11 la", "11 vajta", "11 baje",
           sade 10 (10:30), savva 10 (10:15), paune 11 (10:45), dedh (1:30), adich (2:30)
  periods  morning/sakali, afternoon/dupari, evening/sandhyakali/sanje, night/tonight/ratri
  length   "for 45 minutes", "for 2 hours", "1 tas", "ardha tas", "11 to 12", "11-12:30"
Every guess (am/pm, which day) is listed in the confirmation so nothing is silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

from jarvis.connectors.config import get_tz


class TimeParseError(ValueError):
    pass


@dataclass
class ParsedTime:
    start: datetime
    end: datetime
    tz_name: str
    assumptions: list[str] = field(default_factory=list)

    def confirmation(self) -> str:
        same_day = self.start.date() == self.end.date()
        end = self.end.strftime("%H:%M") if same_day else self.end.strftime("%A %d %b %Y, %H:%M")
        text = f"{self.start.strftime('%A %d %b %Y, %H:%M')} to {end} ({self.tz_name})"
        if self.assumptions:
            text += ". Assumed: " + "; ".join(self.assumptions)
        return text

    def as_tool_text(self) -> str:
        return (f"start: {self.start.isoformat()}\nend: {self.end.isoformat()}\n"
                f"In words: {self.confirmation()}\nConfirm this time with the user before creating the event.")


_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DEVANAGARI_WORDS = {
    "उद्या": "udya", "आज": "aaj", "परवा": "parva", "सकाळी": "sakali", "दुपारी": "dupari",
    "संध्याकाळी": "sandhyakali", "रात्री": "ratri", "वाजता": "vajta", "ला": "la", "साडे": "sade",
    "सव्वा": "savva", "पावणे": "paune", "दीड": "dedh", "अडीच": "adich", "तास": "tas", "पुढच्या": "pudhchya",
    "पुढचा": "pudhcha", "सोमवारी": "somvari", "मंगळवारी": "mangalvari", "बुधवारी": "budhvari",
    "गुरुवारी": "guruvari", "शुक्रवारी": "shukravari", "शनिवारी": "shanivari", "रविवारी": "ravivari",
    "सोमवार": "somvar", "मंगळवार": "mangalvar", "बुधवार": "budhvar", "गुरुवार": "guruvar",
    "शुक्रवार": "shukravar", "शनिवार": "shanivar", "रविवार": "ravivar", "मिनिटे": "minutes", "मिनिटं": "minutes",
}

_WEEKDAYS = [
    ("monday|mon|somvari|somwari|somvar|somwar", 0),
    ("tuesday|tues|tue|mangalvari|mangalwari|mangalvar|mangalwar", 1),
    ("wednesday|wed|budhvari|budhwari|budhvar|budhwar", 2),
    ("thursday|thurs|thur|thu|guruvari|guruwari|guruvar|guruwar", 3),
    ("friday|fri|shukravari|shukrawari|shukravar|shukrawar", 4),
    ("saturday|sat|shanivari|shaniwari|shanivar|shaniwar", 5),
    ("sunday|sun|ravivari|raviwari|ravivar|raviwar", 6),
]
_MONTHS = {m: i for i, names in enumerate(
    ["january jan", "february feb", "march mar", "april apr", "may", "june jun", "july jul",
     "august aug", "september sept sep", "october oct", "november nov", "december dec"], start=1)
    for m in names.split()}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_PERIODS = {
    "morning": "am", "sakali": "am", "sakaali": "am", "sakal": "am",
    "afternoon": "pm", "dupari": "pm", "dupaari": "pm",
    "evening": "pm", "sandhyakali": "pm", "sandhyakal": "pm", "sanje": "pm", "sandhyakaali": "pm",
    "night": "night", "tonight": "night", "ratri": "night", "raatri": "night",
}

_AMPM = r"(?P<ap>a\.?m\.?|p\.?m\.?)"
_HOUR_MARK = r"(?:la|vajta|vajata|wajta|vajle|baje|o'?clock|hrs)"
_TIME_PATTERNS = [
    # Marathi fractions before the hour: sade 10 = 10:30, savva 10 = 10:15, paune 11 = 10:45
    re.compile(rf"\b(?P<frac>sade|saade|savva|sava|paune|pavne)\s+(?P<h>\d{{1,2}})\b(?:\s*{_AMPM})?(?:\s*{_HOUR_MARK})?"),
    re.compile(rf"\b(?P<word>dedh|didh|adich|adhich|adeech)\b(?:\s*{_AMPM})?(?:\s*{_HOUR_MARK})?"),
    re.compile(rf"\b(?P<h>\d{{1,2}})[:.](?P<m>\d{{2}})\s*{_AMPM}?(?:\s*{_HOUR_MARK})?"),
    re.compile(rf"\b(?P<h>\d{{1,2}})\s*{_AMPM}(?:\s*{_HOUR_MARK})?"),
    re.compile(rf"\b(?:at|@)\s*(?P<h>\d{{1,2}})\b(?:\s*{_HOUR_MARK})?"),
    re.compile(rf"\b(?P<h>\d{{1,2}})\s*{_HOUR_MARK}\b"),
    re.compile(r"\b(?P<named>noon|midday|midnight)\b"),
]
_RANGE_SEP = re.compile(r"\s*(?:to|till|until|-|–|te|paryant|parynt)\s*")  # used with .match(text, pos)
_RANGE_START = re.compile(r"\b(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>am|pm)?\s*"
                          r"(?:to|till|until|-|–|te|paryant|parynt)\s*$")
_DURATION = [
    (re.compile(r"\b(?:for\s+)?(?P<n>\d+(?:\.\d+)?)\s*(?:minutes|minute|mins|min|minit|minita|minte)\b"), 1),
    (re.compile(r"\b(?:for\s+)?(?P<n>\d+(?:\.\d+)?)\s*(?:hours|hour|hrs|hr|tas|taas|ghante)\b"), 60),
    (re.compile(r"\b(?:for\s+)?(?:half an hour|ardha tas|ardha taas|1/2 hour)\b"), 30),
    (re.compile(r"\bfor\s+an?\s+hour\b"), 60),
]


def _normalize(text: str) -> str:
    text = text.translate(_DEVANAGARI_DIGITS)
    for dev, latin in _DEVANAGARI_WORDS.items():
        text = text.replace(dev, f" {latin} ")
    text = text.lower().replace(",", " ")
    return re.sub(r"\s+", " ", text).strip()


def _blank(text: str, m: re.Match) -> str:
    return text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]


def _parse_date(text: str, today: date, notes: list[str]) -> tuple[date | None, str, timedelta | None]:
    """Find the day. Returns (date or None, text with the date words removed, relative offset)."""
    m = re.search(r"\bin\s+(?P<n>\d+)\s*(?P<u>minutes|minute|mins|min|hours|hour|hrs|hr|days|day)\b", text)
    if m:
        n, u = int(m.group("n")), m.group("u")
        delta = timedelta(minutes=n) if u.startswith("min") else timedelta(hours=n) if u.startswith("h") else timedelta(days=n)
        if u.startswith(("min", "h")):
            return None, _blank(text, m), delta
        return today + delta, _blank(text, m), None

    m = re.search(r"\b(?:day after tomorrow|parva|parwa|parvaa)\b", text)
    if m:
        return today + timedelta(days=2), _blank(text, m), None
    m = re.search(r"\b(?:tomorrow|tmrw|tmr|udya|udyaa|udyaa?ch)\b", text)
    if m:
        return today + timedelta(days=1), _blank(text, m), None
    m = re.search(r"\b(?:today|aaj|aj|aajch)\b", text)
    if m:
        return today, _blank(text, m), None

    m = re.search(r"\b(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})\b", text)
    if m:
        return _mkdate(int(m.group("y")), int(m.group("mo")), int(m.group("d"))), _blank(text, m), None
    m = (re.search(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RE})\b(?:\s+(?P<y>\d{{4}}))?", text)
         or re.search(rf"\b(?P<mon>{_MONTH_RE})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?:\s+(?P<y>\d{{4}}))?", text))
    if m:
        return _with_year(int(m.group("d")), _MONTHS[m.group("mon")], m.group("y"), today, notes), _blank(text, m), None
    m = re.search(r"\b(?P<d>\d{1,2})/(?P<mo>\d{1,2})(?:/(?P<y>\d{2,4}))?\b", text)
    if m:
        y = m.group("y")
        if y and len(y) == 2:
            y = "20" + y
        notes.append(f"{m.group(0)} read as day/month")
        return _with_year(int(m.group("d")), int(m.group("mo")), y, today, notes), _blank(text, m), None

    for names, wd in _WEEKDAYS:
        m = re.search(rf"\b(?P<next>next|pudhcha|pudhchya|pudhil)?\s*(?:{names})\b", text)
        if m:
            ahead = (wd - today.weekday()) % 7
            if m.group("next") and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead), _blank(text, m), None
    return None, text, None


def _mkdate(y: int, mo: int, d: int) -> date:
    try:
        return date(y, mo, d)
    except ValueError as e:
        raise TimeParseError(f"not a real date: {y}-{mo:02d}-{d:02d}") from e


def _with_year(d: int, mo: int, y: str | None, today: date, notes: list[str]) -> date:
    if y:
        return _mkdate(int(y), mo, d)
    found = _mkdate(today.year, mo, d)
    if found < today:
        notes.append("that date has passed this year, so next year")
        found = _mkdate(today.year + 1, mo, d)
    return found


@dataclass
class _Clock:
    hour: int
    minute: int
    ampm: str | None  # "am" | "pm" | None
    end: int  # index in the text after the match
    start: int = 0


_BARE_HOUR = re.compile(r"\b(?P<h>\d{1,2})\b(?![/:.]\d)")


def _match_time(text: str, start: int = 0, anchored: bool = False) -> _Clock | None:
    """Earliest time expression; on a tie the more specific pattern (listed first) wins.

    A bare number ("udya 11") is used only when nothing more specific is found; by then
    the date and the duration have been removed from the text.
    """
    found = _match_patterns(_TIME_PATTERNS, text, start, anchored)
    return found or _match_patterns([_BARE_HOUR], text, start, anchored)


def _match_patterns(patterns: list[re.Pattern], text: str, start: int, anchored: bool) -> _Clock | None:
    best: tuple[int, _Clock] | None = None
    for pat in patterns:
        m = pat.match(text, start) if anchored else pat.search(text, start)
        if not m:
            continue
        g = m.groupdict()
        ap = (g.get("ap") or "").replace(".", "") or None
        if g.get("named"):
            clock = _Clock(0 if g["named"] == "midnight" else 12, 0, "am" if g["named"] == "midnight" else "pm", m.end())
        elif g.get("word"):
            hour = 1 if g["word"] in ("dedh", "didh") else 2
            clock = _Clock(hour, 30, ap, m.end())
        elif g.get("frac"):
            h = int(g["h"])
            if g["frac"] in ("sade", "saade"):
                clock = _Clock(h, 30, ap, m.end())
            elif g["frac"] in ("savva", "sava"):
                clock = _Clock(h, 15, ap, m.end())
            else:  # paune: a quarter before
                clock = _Clock((h - 1) or 12, 45, ap, m.end())
        else:
            clock = _Clock(int(g["h"]), int(g.get("m") or 0), ap, m.end())
        if clock.hour > 23 or clock.minute > 59:
            continue
        pos = m.start("h") if g.get("h") else m.start()
        clock.start = m.start()
        if best is None or pos < best[0]:
            best = (pos, clock)
    return best[1] if best else None


def _to_24h(c: _Clock, period: str | None, notes: list[str], label: str) -> tuple[int, int, bool]:
    """Hour in 24h form, minute, and whether it falls after midnight (next day)."""
    h = c.hour
    if c.ampm == "am":
        return (0 if h == 12 else h), c.minute, False
    if c.ampm == "pm":
        return (h if h >= 12 else h + 12), c.minute, False
    if h >= 13 or h == 0:
        return h, c.minute, False
    if period == "am":
        return (0 if h == 12 else h), c.minute, False
    if period == "pm":
        return (h if h == 12 else h + 12), c.minute, False
    if period == "night":
        if h == 12:
            return 0, c.minute, True
        if h <= 4:
            return h, c.minute, True
        return h + 12, c.minute, False
    if 1 <= h <= 6:
        notes.append(f"{label} {h}:{c.minute:02d} read as pm (say am if you meant morning)")
        return h + 12, c.minute, False
    if 7 <= h <= 11:
        notes.append(f"{label} {h}:{c.minute:02d} read as am (say pm if you meant evening)")
    return h, c.minute, False


def parse_when(text: str, now: datetime, tz_name: str | None = None, default_minutes: int = 30) -> ParsedTime:
    """Parse an event time. `now` should be timezone-aware; naive is taken as local time in tz_name."""
    tz: tzinfo = get_tz(tz_name)
    tz_label = tz_name or "Asia/Kolkata"
    now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    notes: list[str] = []
    s = _normalize(text)
    if not s:
        raise TimeParseError("no time given")

    day, rest, relative = _parse_date(s, now.date(), notes)

    duration = None
    for pat, unit in _DURATION:
        m = pat.search(rest)
        if m:
            n = float(m.group("n")) if "n" in pat.groupindex else 1.0
            duration = timedelta(minutes=n * unit)
            rest = _blank(rest, m)
            break

    if relative is not None:
        start = (now + relative).replace(second=0, microsecond=0)
        end = start + (duration or timedelta(minutes=default_minutes))
        return ParsedTime(start, end, tz_label, notes)

    period = None
    for word, p in _PERIODS.items():
        if re.search(rf"\b{word}\b", rest):
            period = p
            if word == "tonight" and day is None:
                day = now.date()
            break

    clock = _match_time(rest)
    if clock is None:
        if day is not None:
            raise TimeParseError("found the day but not the time; what time?")
        raise TimeParseError(f"could not find a day or time in {text!r}")

    end_clock = None
    pre = _RANGE_START.search(rest[:clock.start])
    if pre:  # "11 to 12:30 pm": the specific time found is the end of a range
        end_clock = clock
        clock = _Clock(int(pre.group("h")), int(pre.group("m") or 0), pre.group("ap"), pre.end(), pre.start())
    else:
        sep = _RANGE_SEP.match(rest, clock.end)
        if sep:
            end_clock = _match_time(rest, sep.end(), anchored=True)
    if end_clock:
        if end_clock and clock.ampm is None and end_clock.ampm is not None and clock.hour <= 12:
            # "3 to 4 pm": the start shares the pm. "11 to 12:30 pm": 11 is am. "10 to 1 pm": guess.
            if end_clock.hour == 12:
                clock.ampm = "am" if end_clock.ampm == "pm" and clock.hour < 12 else None
            elif clock.hour <= end_clock.hour:
                clock.ampm = end_clock.ampm

    h, mi, next_day = _to_24h(clock, period, notes, "start")
    if day is None:
        day = now.date()
        candidate = datetime.combine(day, time(h, mi), tz)
        if next_day:
            candidate += timedelta(days=1)
        if candidate <= now:
            candidate += timedelta(days=1)
            notes.append("that time has passed today, so tomorrow")
        start = candidate
    else:
        start = datetime.combine(day, time(h, mi), tz) + (timedelta(days=1) if next_day else timedelta(0))
        if start.date() == now.date() and start <= now:
            weekday_named = any(re.search(rf"\b(?:{n})\b", s) for n, _ in _WEEKDAYS)
            if weekday_named:
                start += timedelta(days=7)
                notes.append("that time has passed today, so next week")
    if start < now:
        notes.append("WARNING: this time is in the past")

    if end_clock:
        if end_clock.ampm is None and clock.ampm is None and period is None and end_clock.hour < 13:
            # end follows the start's half of the day: "3 to 4" (pm) stays pm
            eh = end_clock.hour + (12 if start.hour >= 12 and end_clock.hour < 12 else 0)
            end = start.replace(hour=eh % 24, minute=end_clock.minute)
        else:
            eh, emi, _ = _to_24h(end_clock, period, [], "end")
            end = start.replace(hour=eh, minute=emi)
        if end <= start:
            end += timedelta(hours=12) if end + timedelta(hours=12) > start else timedelta(days=1)
    else:
        end = start + (duration or timedelta(minutes=default_minutes))
        if duration is None:
            notes.append(f"length {default_minutes} minutes")
    return ParsedTime(start, end, tz_label, notes)


def parse_iso(value: str, tz_name: str | None = None) -> datetime:
    """An ISO 8601 date-time; naive values are taken as local time in tz_name."""
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise TimeParseError(f"{value!r} is not an ISO date-time; call parse_time first") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=get_tz(tz_name))


def parse_day(text: str, today: date) -> date | None:
    """Only the day in a phrase ("tomorrow", "somvar", "12 Oct"), or None."""
    return _parse_date(_normalize(text), today, [])[0]
