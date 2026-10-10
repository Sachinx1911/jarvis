"""Deterministic "is this sensitive?" check for memories (PLAN.md 5.9).

The memory prompts ask the model to mark health and medical details, money, identity
document contents or numbers, other people's phone numbers, emails or addresses, and
political opinions as "sensitive" (P2). A model can miss that, so every memory built from
model output also goes through this check (jarvis/memory/extract.py). It can only RAISE a
memory to "sensitive": it never lowers one and never touches "secret" (secrets are refused
by jarvis.privacy and the memory store).

Family members' names, where things are kept, schedules and preferences stay "normal"
(Sachin's decision, 2026-10-10). So the lists hold specific terms only. Generic words are
left out or need a qualifier: "party" (birthday party), "bank", "medicine" (the medicine
box is in the cupboard), "doctor", "sugar" (no sugar in tea), "address" (address me as
sir), "passport" (where the passport is kept), "email" (never send email without asking).

Term syntax: lowercase; "stem*" also matches longer words ("diagnos*" -> diagnosed,
"दवाखान*" -> दवाखान्यात); a space matches any whitespace; anything else is a whole word.
Each category has English, romanized Marathi and Devanagari Marathi terms; the patterns
catch readings, doses and numbers. The text is lowercased, NFC-normalized, has zero-width
joiners removed and Devanagari digits turned into ASCII digits before matching.

Known trade-offs (raise-only, so a miss is the model's label and a false positive costs
little): the user's own phone, email or address is caught too, and a place named after a
hospital marks the memory sensitive. Sachin can lower a memory by hand in the dashboard.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from jarvis.memory.model import Memory

_W = "[\\wऀ-ॣ०-ॿ]"   # a word character, Devanagari vowel signs included (as translit.WORD_RE)
_LEFT = f"(?<!{_W})"
_RIGHT = f"(?!{_W})"

# Per category: English lines first, then romanized Marathi, then Devanagari Marathi.
TERMS: dict[str, tuple[str, ...]] = {
    "health": (
        "diagnos*", "prescription*", "prescribed", "medication*", "dosage", "symptom*",
        "blood pressure", "bp", "hypertension", "blood sugar", "sugar level*", "diabet*", "insulin", "hba1c",
        "thyroid*", "cholesterol", "hospital", "hospitals", "hospitalis*", "hospitaliz*", "surgery", "surgeries",
        "cancer*", "tumor*", "tumour*", "asthma*", "allerg*", "migraine*", "fracture*", "pregnan*", "dialysis",
        "chemotherapy", "physiotherap*", "psychiatr*", "therapist*", "antidepressant*", "blood test*",
        "mri", "ecg", "x-ray*", "xray*",
        "davakhan*", "dawakhan*", "aajar*", "ajari", "raktadab*", "madhumeh*", "upchar*",
        "आजार*", "उपचार*", "दवाखान*", "हॉस्पिटल*", "रुग्णालय*", "रक्तदाब*", "बीपी", "मधुमेह*", "शुगर*",
        "डायबिटीज*", "थायरॉ*", "कॅन्सर*", "कर्करोग*", "शस्त्रक्रिया*", "ऑपरेशन*", "प्रिस्क्रिप्शन*",
        "ॲलर्जी*", "अॅलर्जी*", "एलर्जी*", "इंजेक्शन*", "गर्भवती*",
    ),
    "money": (
        "salar*", "loan*", "emi", "emis", "debt*", "owe", "owes", "owed", "income*", "pension*", "savings",
        "investment*", "bank balance", "account balance", "bank account*", "ifsc", "credit score", "cibil*",
        "fixed deposit*", "mutual fund*", "net worth", "ctc", "lpa",
        "pagar*", "karj", "karja", "karjach*", "karjav*", "karz", "karza", "karzach*", "karzav*",  # not Karjat
        "hapta", "hapte", "haptya*", "udhari*", "udhaari*", "vyaj*", "vyaaj*", "guntavnuk*",
        "पगार*", "कर्ज", "कर्जा*", "कर्जे", "हप्त*", "उधार*", "व्याज*", "गुंतवणूक*", "गुंतवणुक*", "उत्पन्न*",
        "पेन्शन*", "ईएमआय", "बँक बॅलन्स", "बँक खात*",
    ),
    "identity": (),   # patterns only: a document word followed by "number", "no", "क्रमांक"...
    "contact": (
        "pin code", "pincode", "home address*", "postal address*", "residential address*",
        "patta",
        "पत्ता", "पत्त्या*", "पिन कोड", "पिनकोड",
    ),
    "politics": (
        "politic*", "election*", "vote", "votes", "voted", "voting", "voter*", "ballot*", "manifesto*",
        "mla", "mlas", "corporator*", "lok sabha", "vidhan sabha", "loksabha", "vidhansabha",
        "bjp", "congress", "shiv sena", "shivsena", "ncp", "mns", "communist*",
        "left wing", "right wing", "left-wing", "right-wing",
        "rajkaran*", "rajkiya", "matdan*", "nivadnuk*", "nivdnuk*", "umedvar*", "umedwar*", "bhajap",
        "rashtravadi", "aamdar*", "amdar*", "khasdar*", "nagarsevak*",
        "राजकारण*", "राजकीय*", "मतदान*", "निवडणूक*", "निवडणुक*", "उमेदवार*", "भाजप*", "काँग्रेस*", "कॉंग्रेस*",
        "शिवसेन*", "राष्ट्रवादी*", "मनसे", "आमदार*", "खासदार*", "नगरसेवक*",
    ),
}

_ID_DOC = (r"(?:passport|a{1,2}dha{1,2}r|pan|voter id|voter card|driving licen[cs]e|licen[cs]e|dl"
           r"|आधार|पासपोर्ट|पॅन|ओळखपत्र|लायसन्स|लायसेन्स|परवाना)")

PATTERNS: dict[str, tuple[str, ...]] = {
    "health": (
        r"(?<![\d.])\d{1,4}(?:\.\d+)?\s?mg(?![a-z])",                     # a dose: 500 mg, 2.5mg
        r"mg\s*/\s*dl",
        r"sugar\s*(?:level|reading)?\s*(?:is|was|:|=|-)?\s*\d{2,3}(?!\d)",  # a sugar reading: sugar 140
    ),
    "money": (),
    "identity": (
        _LEFT + _ID_DOC + r"\s*(?:card\s*|कार्ड\s*)?(?:'s\s*|cha\s*|chi\s*|che\s*|chya\s*|चा\s*|ची\s*|चे\s*|च्या\s*)?"
        r"(?:number|no(?![a-z])|num(?![a-z])|#|expiry|expires|validity|नंबर|क्रमांक)",
    ),
    "contact": (
        r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",                                    # an email address
        r"(?<![\d+])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",           # an Indian mobile number
        r"(?<!\w)\+\d{1,3}[\s-]?\d[\d\s-]{6,13}\d(?!\d)",                   # an international number
        r"(?<!\d)0\d{2,4}[\s-]\d{6,8}(?!\d)",                               # a landline with STD code
        r"(?:phone|mobile|contact|whatsapp|cell|landline|फोन|मोबाईल|मोबाइल|संपर्क)\s*"
        r"(?:number|no\.?|नंबर|क्रमांक)\D{0,6}\d",                           # "mobile number is 2567..."
        _LEFT + r"(?:his|her|their)\s+address",
        _LEFT + r"(?<!ip )(?<!mac )(?<!web )address\s*(?:is(?![a-z])|:)",          # not "IP address is"
        _LEFT + r"(?:flat|house|plot|bungalow|room)\s*(?:no\.?|number|#)\s*[a-z]?-?\d",
    ),
    "politics": (
        _LEFT + r"(?:election|party|mla|lok sabha|vidhan sabha|independent|bjp|congress)\s+candidates?" + _RIGHT,
        _LEFT + r"party\s+(?:worker|member|office|ticket)s?" + _RIGHT,
    ),
}

_TRANSLATE = {**{ord(c): None for c in "\u200c\u200d"},   # zero-width (non-)joiners: spellings meet
              **{0x0966 + i: ord(str(i)) for i in range(10)}}     # ९८७६ -> 9876


def _term(term: str) -> str:
    term = unicodedata.normalize("NFC", term)
    stem = term.endswith("*")
    body = r"\s+".join(re.escape(part) for part in term.rstrip("*").split())
    return body + (f"{_W}*" if stem else "")


def _compile(category: str) -> re.Pattern[str]:
    parts = []
    if TERMS[category]:
        parts.append(_LEFT + "(?:" + "|".join(_term(t) for t in TERMS[category]) + ")" + _RIGHT)
    parts += [unicodedata.normalize("NFC", p) for p in PATTERNS[category]]
    return re.compile("|".join(f"(?:{p})" for p in parts))


CATEGORIES = tuple(TERMS)
_COMPILED = {c: _compile(c) for c in CATEGORIES}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").translate(_TRANSLATE).lower()


def sensitive_categories(text: str) -> list[str]:
    """The sensitive categories found in `text`, in CATEGORIES order (empty if none)."""
    text = normalize(text)
    return [c for c in CATEGORIES if _COMPILED[c].search(text)]


def _memory_text(mem: Memory) -> Iterable[str]:
    return (mem.name, mem.subject, mem.description, mem.when_to_use, mem.summary_en, mem.keywords,
            mem.evidence, mem.body)


def raise_sensitivity(mem: Memory) -> list[str]:
    """Mark `mem` "sensitive" when its text falls in a sensitive category. Returns the
    categories when it raised the memory, else []. Never lowers; leaves "secret" alone."""
    if mem.sensitivity not in ("public", "normal"):
        return []
    found = sensitive_categories(" | ".join(_memory_text(mem)))
    if found:
        mem.sensitivity = "sensitive"
    return found


def inherit_sensitive(mem: Memory, other: Memory) -> bool:
    """A memory merged with, or replacing, a sensitive memory stays sensitive. True if raised."""
    if other.sensitivity == "sensitive" and mem.sensitivity in ("public", "normal"):
        mem.sensitivity = "sensitive"
        return True
    return False
