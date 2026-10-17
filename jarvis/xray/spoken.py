"""Spoken addresses and teardown intents (PLAN.md 18.1 item 5).

"igloo dot inc" -> https://igloo.inc; "stripe dot com slash pricing" -> https://stripe.com/pricing;
"localhost colon three thousand" -> http://localhost:3000 (localhost is allowed: Sachin's own dev
server). Marathi: "डॉट" is dot, Devanagari digits are digits. Pure text work, no network.
"""

from __future__ import annotations

import re

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
          "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
          "ninety": 90,
          # Marathi (romanized and Devanagari) for the few numbers a port is said with
          "शून्य": 0, "एक": 1, "दोन": 2, "तीन": 3, "चार": 4, "पाच": 5, "सहा": 6, "सात": 7, "आठ": 8, "नऊ": 9,
          "ek": 1, "don": 2, "teen": 3, "char": 4, "pach": 5, "saha": 6, "saat": 7, "aath": 8, "nau": 9}
_SCALES = {"hundred": 100, "thousand": 1000, "शंभर": 100, "हजार": 1000, "hajar": 1000, "shambhar": 100}
_SEPARATORS = ((r"\s*\b(?:dot|डॉट|dot\.)\b\s*", "."), (r"\s*\b(?:slash|स्लॅश|स्लॅश)\b\s*", "/"),
               (r"\s*\b(?:colon|कोलन)\b\s*", ":"), (r"\s*\b(?:dash|hyphen|हायफन)\b\s*", "-"))
_URL = re.compile(r"(?:(https?)://)?((?:[a-z0-9-]+\.)+[a-z]{2,}|localhost)(?::(\d{2,5}))?(/[^\s]*)?", re.I)
# (?<!\S) / (?!\S) instead of \b: Devanagari vowel signs are not \w, so \b fails after them.
_SITE = re.compile(r"(?<!\S)(this|the current|हि|ही|ह्या|या|हे)\s*(site|page|website|tab|साइट|साईट|पेज|वेबसाइट)(?!\S)", re.I)


def _numbers_to_digits(text: str) -> str:
    """Runs of number words become digits: "three thousand" -> 3000, "eighty eighty" -> 8080."""
    words = text.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i].lower()
        if w not in _UNITS and w not in _SCALES:
            out.append(words[i])
            i += 1
            continue
        # one group = [tens] [unit] [scale]...; a unit that cannot join the group starts a new one,
        # so "eighty eighty" is 8080 and "eight zero eight zero" is 8080, "three thousand" is 3000
        total, current, parts = 0, None, []
        while i < len(words) and (words[i].lower() in _UNITS or words[i].lower() in _SCALES):
            w = words[i].lower()
            if w in _SCALES:
                total += (current if current is not None else 1) * _SCALES[w]
                current = None
            else:
                unit = _UNITS[w]
                if current is None and total == 0:
                    current = unit
                elif current is not None and current >= 20 and current % 10 == 0 and 0 < unit < 10:
                    current += unit                       # "twenty three"
                elif current is None and total:
                    current = unit                        # "three thousand five"
                else:
                    parts.append(str(total + (current or 0)))
                    total, current = 0, unit
            i += 1
        parts.append(str(total + (current or 0)))
        out.append("".join(parts))
    return " ".join(out)


def parse_spoken_address(text: str) -> str | None:
    """A web address from spoken or typed words, or None when there is none."""
    if not text or not text.strip():
        return None
    t = text.translate(_DEV_DIGITS).strip()
    t = _numbers_to_digits(t)
    for pattern, sep in _SEPARATORS:   # the spoken word and the spaces around it become the sign
        t = re.sub(pattern, sep, t, flags=re.I)
    for m in _URL.finditer(t):
        scheme, host, port, path = m.group(1), m.group(2).lower(), m.group(3), m.group(4) or ""
        host = host.strip(".")
        if host != "localhost" and not re.search(r"\.[a-z]{2,}$", host):
            continue
        if host.replace(".", "").isdigit():
            continue
        scheme = (scheme or ("http" if host == "localhost" else "https")).lower()
        path = path.rstrip(".,;:!?)")
        if path and not path.startswith("/"):
            path = "/" + path
        return f"{scheme}://{host}{':' + port if port else ''}{path}"
    return None


# ---- intents ----

_INTENTS_EN = (
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?(?:please |can you |could you )?reverse[- ]?engineer (?P<target>.+?)(?: for me| please)?[.?!]*$",
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?(?:please |can you |could you )?(?:do a |run a )?tear ?down (?:of |on )?(?P<target>.+?)(?: for me| please)?[.?!]*$",
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?how (?:does|do|did|is) (?P<target>.+?) (?:do|make|build|pull off|achieve) (?:that|this|it|those|these)\b.*$",
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?what(?:'s| is| was) (?P<target>.+?) (?:built|made) (?:with|of|on|in)[.?!]*$",
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?how (?:is|was) (?P<target>.+?) (?:built|made)[.?!]*$",
    r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?what (?:tech|stack|framework|library|libraries|technology)\b.* (?:does|is) (?P<target>.+?) (?:use|using|built with|made with|run on|running on)[.?!]*$",
)
_INTENTS_MR = (
    r"^(?:जार्विस[, ]+)?(?P<target>.+?)\s+(?:कसं|कसे|कशी|कसा)\s+(?:बनवलंय|बनवलं|बनवली|बनवले|बनवलेय|बनवलाय|बनलंय|बनलं|केलंय|केलं)(?:\s.*)?[.?!]*$",
    r"^(?:जार्विस[, ]+)?(?P<target>.+?)\s*(?:चं|चा|ची|चे|च)\s+(?:teardown|टियरडाउन|reverse engineer|रिव्हर्स इंजिनिअर)(?:ing)?\s*(?:कर|करा|कर ना|करशील का|करशील)?[.?!]*$",
    r"^(?:जार्विस[, ]+)?(?P<target>.+?)\s+(?:teardown|reverse engineer)\s+(?:कर|करा|करशील का)[.?!]*$",
    r"^(?:जार्विस[, ]+)?(?P<target>.+?)\s+(?:कशात|कशाने|कशावर|कोणत्या\s+\S+\s*(?:मध्ये|ने|वर))\s+(?:बनवलंय|बनवलं|बनवली|बनवले|बनलंय|बनलं)(?:\s.*)?[.?!]*$",
)
_STRIP_TARGET = re.compile(r"^(?:the |that |this |a )?(?:website |site |page |homepage of |home page of )?(.+?)(?:'s (?:website|site|homepage|home ?page|landing page))?$", re.I)


def _normalize(text: str) -> str:
    return " ".join(text.replace("‍", "").split()).strip()


def teardown_intent(text: str) -> tuple[str | None, str] | None:
    """(target, question) when the sentence asks for a teardown; None otherwise. The target is a
    web address, "this site" (the front browser tab) or None when the words name a site Jarvis
    cannot turn into an address itself (the brain's `teardown` tool may still know it)."""
    t = _normalize(text)
    if not t:
        return None
    target_words: str | None = None
    for pat in _INTENTS_EN:
        m = re.match(pat, t, re.I)
        if m:
            target_words = m.group("target")
            break
    if target_words is None:
        for pat in _INTENTS_MR:
            m = re.match(pat, t)
            if m:
                target_words = m.group("target")
                break
    if target_words is None:
        return None
    target_words = target_words.strip(" .,:;!?\"'")
    if _SITE.search(target_words) or _SITE.search(t):
        return "this site", t
    url = parse_spoken_address(target_words)
    if url:
        return url, t
    stripped = _STRIP_TARGET.match(target_words)
    return (parse_spoken_address(stripped.group(1)) if stripped else None), t
