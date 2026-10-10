"""Approximate Devanagari <-> romanized Marathi, for search only (no new dependency).

Sachin types Marathi in Devanagari and in romanized form ("माझा भाऊ" / "maza bhau"),
and memories are written in whichever script he used. Search must match either way.

Approach: every word is reduced to one *canonical romanized form*, a lossy ASCII key:
- Devanagari is romanized with simple rules (short and long vowels collapse, the
  inherent "a" is dropped at the end of a word and, in a second variant, inside words
  as Marathi speakers do: करतो -> "karto").
- Romanized words are normalized the same way: "aai" -> "ai", "majha" -> "maza",
  "wadil" -> "vadil", "pakka" -> "paka".
So "आई", "aai" and "aai" all meet at "ai". Index time adds these keys to the search
text; query time adds them to the query words.

to_devanagari() goes the other way (romanized -> one plausible Devanagari spelling).
It is a rough guess, used only to add a Devanagari keyword next to a romanized one.
Approximate is fine: trigram search absorbs small spelling differences.
"""

from __future__ import annotations

import re

# A word: letters/digits plus the whole Devanagari block (matras, virama, nukta) except
# the danda signs. Python's \w alone splits Devanagari words at every vowel sign.
WORD_RE = re.compile(r"[\wऀ-ॣ०-ॿ]+", re.UNICODE)
_DEVA_RE = re.compile(r"[ऀ-ॿ]")

_VIRAMA = "्"
_NUKTA = "़"
_ANUSVARA = "ं"
_CHANDRABINDU = "ँ"
_VISARGA = "ः"

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "ch", "ज": "j", "झ": "z", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v", "ऱ": "r",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y",
}
_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ru",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "a", "ऍ": "a",
}
_MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ru",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "a",  # ॅ is the English "a" of प्लॅन (plan)
}
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_LABIALS = ("p", "f", "b", "m")


def is_devanagari(word: str) -> bool:
    return bool(_DEVA_RE.search(word))


def words(text: str) -> list[str]:
    """Lowercased words, keeping Devanagari words whole."""
    return WORD_RE.findall(text.lower())


def canonical_roman(word: str) -> str:
    """Normalize a romanized (or English) word to the shared lossy key."""
    w = word.lower()
    w = w.replace("ee", "i").replace("oo", "u").replace("w", "v").replace("q", "k")
    w = w.replace("chh", "ch").replace("ph", "f").replace("jh", "z").replace("x", "ks")
    w = re.sub(r"(.)\1+", r"\1", w)          # aa -> a, kk -> k
    return w


def _aksharas(word: str) -> list[dict]:
    """Split a Devanagari word into syllable records: consonant, vowel, how the vowel came."""
    out: list[dict] = []
    chars = [c for c in word if c != _NUKTA]
    i = 0
    while i < len(chars):
        c = chars[i]
        if c in _CONSONANTS:
            rec = {"c": _CONSONANTS[c], "v": "a", "kind": "inherent", "tail": ""}
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt == _VIRAMA:
                rec["v"], rec["kind"] = "", "virama"
                i += 1
            elif nxt in _MATRAS:
                rec["v"], rec["kind"] = _MATRAS[nxt], "matra"
                i += 1
            out.append(rec)
        elif c in _INDEPENDENT_VOWELS:
            out.append({"c": "", "v": _INDEPENDENT_VOWELS[c], "kind": "vowel", "tail": ""})
        elif c in (_ANUSVARA, _CHANDRABINDU):
            if out:
                out[-1]["tail"] += "n"
        elif c == _VISARGA:
            if out:
                out[-1]["tail"] += "h"
        elif c in _DIGITS:
            out.append({"c": _DIGITS[c], "v": "", "kind": "digit", "tail": ""})
        elif c.isascii() and c.isalnum():
            out.append({"c": c, "v": "", "kind": "digit", "tail": ""})
        # other marks (avagraha, stray signs) are dropped
        i += 1
    return out


def _render(recs: list[dict], medial: bool) -> str:
    n = len(recs)
    drop = [False] * n
    # Final schwa: dropped in words of two or more syllables. After a consonant cluster
    # (मित्र "mitra", प्रोजेक्ट "projekt") both are heard, so only the medial variant drops it.
    last = n - 1
    if n > 1 and recs[last]["kind"] == "inherent" and not recs[last]["tail"] \
            and (medial or recs[last - 1]["kind"] != "virama"):
        drop[last] = True
    if medial:
        for i in range(1, n - 1):
            r, prev, nxt = recs[i], recs[i - 1], recs[i + 1]
            if r["kind"] != "inherent" or r["tail"]:
                continue
            if not prev["v"] or drop[i - 1] or prev["kind"] == "digit":
                continue
            if nxt["c"] and nxt["kind"] in ("matra", "virama") and nxt["kind"] != "digit":
                drop[i] = True
    parts: list[str] = []
    for i, r in enumerate(recs):
        v = "" if drop[i] else r["v"]
        tail = r["tail"]
        if tail.startswith("n") and i + 1 < n and recs[i + 1]["c"].startswith(_LABIALS):
            tail = "m" + tail[1:]
        parts.append(r["c"] + v + tail)
    text = "".join(parts)
    text = text.replace("jn", "dny")  # ज्ञ is said "dny" in Marathi (ज्ञान = dnyan)
    return canonical_roman(text)


def roman_forms(word: str) -> list[str]:
    """Canonical romanized keys of one word (1 or 2 variants; empty for an empty word)."""
    if not word:
        return []
    if not is_devanagari(word):
        return [canonical_roman(word)]
    recs = _aksharas(word)
    if not recs:
        return []
    out = [_render(recs, medial=True), _render(recs, medial=False)]
    return [w for w in dict.fromkeys(out) if w]


def to_roman(text: str) -> str:
    """Romanize every Devanagari word of a text (first variant); other words are kept."""
    return re.sub(WORD_RE, lambda m: roman_forms(m.group())[0] if is_devanagari(m.group()) and roman_forms(m.group())
                  else m.group(), text)


# ---- romanized -> Devanagari (rough) ----

_R_CONS = [
    ("ksh", "क्ष"), ("dny", "ज्ञ"), ("kh", "ख"), ("gh", "घ"), ("chh", "छ"), ("ch", "च"), ("jh", "झ"),
    ("th", "थ"), ("dh", "ध"), ("ph", "फ"), ("bh", "भ"), ("sh", "श"),
    ("k", "क"), ("g", "ग"), ("j", "ज"), ("z", "झ"), ("t", "त"), ("d", "द"), ("n", "न"),
    ("p", "प"), ("f", "फ"), ("b", "ब"), ("m", "म"), ("y", "य"), ("r", "र"), ("l", "ल"),
    ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"), ("c", "क"), ("q", "क"), ("x", "क्स"),
]
_R_VOWELS = [  # (roman, independent, matra)
    ("aa", "आ", "ा"), ("ai", "ऐ", "ै"), ("au", "औ", "ौ"), ("ee", "ई", "ी"), ("ii", "ई", "ी"),
    ("oo", "ऊ", "ू"), ("uu", "ऊ", "ू"), ("a", "अ", ""), ("i", "इ", "ि"), ("u", "उ", "ु"),
    ("e", "ए", "े"), ("o", "ओ", "ो"),
]


def to_devanagari(word: str) -> str:
    """One plausible Devanagari spelling of a romanized word ("" if it has no letters)."""
    w = word.lower()
    if not w or not w.isascii() or not w.isalpha():
        return ""
    out: list[str] = []
    i = 0
    after_consonant = False
    while i < len(w):
        for rom, dev in _R_CONS:
            if w.startswith(rom, i):
                if after_consonant:
                    out.append(_VIRAMA)
                out.append(dev)
                after_consonant = True
                i += len(rom)
                break
        else:
            for rom, ind, matra in _R_VOWELS:
                if w.startswith(rom, i):
                    if after_consonant:
                        # a final short "a" in romanized Marathi is usually a long आ (maza = माझा)
                        if rom == "a" and i + 1 == len(w) and len(w) > 2:
                            out.append("ा")
                        else:
                            out.append(matra)
                    else:
                        out.append(ind)
                    after_consonant = False
                    i += len(rom)
                    break
            else:
                i += 1  # unknown character
    return "".join(out)


def script_forms(word: str) -> list[str]:
    """Other-script and canonical forms of a word, not including the word itself."""
    w = word.lower()
    forms = roman_forms(w)
    if not is_devanagari(w) and w.isalpha():
        dev = to_devanagari(w)
        if dev:
            forms.append(dev)
    return [f for f in dict.fromkeys(forms) if f and f != w]


def expand_words(ws: list[str], stopwords: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Query expansion: each word plus its canonical romanized key(s). A Devanagari word whose
    romanized key is a stopword (आहे -> ahe) is dropped with it."""
    out: list[str] = []
    for w in ws:
        keys = roman_forms(w)
        if is_devanagari(w) and keys and keys[0] in stopwords:
            continue
        if w not in stopwords:
            out.append(w)
        out.extend(k for k in keys if k not in stopwords and len(k) >= 2)
    return list(dict.fromkeys(out))


def _stem(key: str) -> str:
    """A romanized key without its last vowels and a final nasal ("pustakan" -> "pustak"), so a
    substring search matches other inflections. Only when 4+ letters remain."""
    stem = key.rstrip("aeiou")
    if stem.endswith("n") and len(stem) > 4 and stem[-2] in "aeiou":
        stem = stem[:-1].rstrip("aeiou")
    return stem if len(stem) >= 4 else key


def text_keys(text: str) -> str:
    """Every word of a text as its canonical romanized key(s): the text as the other script
    would spell it, for substring (trigram) search over raw chat lines."""
    out: list[str] = []
    for w in words(text):
        out.extend(roman_forms(w))
    return " ".join(out)


def query_keys(ws: list[str]) -> list[str]:
    """Canonical keys and their stems for a substring search over text_keys()."""
    out: list[str] = []
    for w in ws:
        for k in roman_forms(w):
            out.append(k)
            out.append(_stem(k))
    return [k for k in dict.fromkeys(out) if len(k) >= 3]


def index_variants(text: str, limit: int = 400) -> str:
    """Extra search words for an index entry: canonical romanized keys of every word that
    differ from the word itself. Not stored in the memory file, only in the index."""
    extra: list[str] = []
    for w in words(text):
        for k in roman_forms(w):
            if k != w and len(k) >= 2:
                extra.append(k)
    return " ".join(list(dict.fromkeys(extra))[:limit])


def add_script_forms(keywords: str, english_text: str = "", limit: int = 30) -> str:
    """Keywords plus the other-script form of each Marathi keyword (write time).

    Devanagari keywords get their romanized key; romanized keywords get a Devanagari
    guess. Words that appear in `english_text` (the English summary) are taken to be
    English and get no Devanagari guess."""
    english = set(words(english_text))
    base = keywords.split()
    out = list(base)
    for w in base:
        lw = w.lower()
        if is_devanagari(lw):
            out.extend(roman_forms(lw)[:1])
        elif lw.isascii() and lw.isalpha() and len(lw) >= 3 and lw not in english:
            dev = to_devanagari(lw)
            if dev:
                out.append(dev)
    return " ".join(list(dict.fromkeys(out))[:max(limit, len(base))])
