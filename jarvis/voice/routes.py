"""The voice-route table (PLAN.md 18.1, Part One row 02 and 05): sentences handled before the brain.

- stop: the instant words (stop / wait / थांब) silence Jarvis at once; no model call.
- remember: "remember that ..." / "लक्षात ठेव ..." saves a memory through the /remember path.
- show_last_teardown: reads the newest teardown note's summary.
- teardown: "reverse engineer X", "tear down X", "how does X do that", "X कसं बनवलंय" ...

A route matches whole sentences only; anything else goes to the brain as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from jarvis.voice.approval import normalize
from jarvis.xray.spoken import teardown_intent

# The instant words. loop.py re-exports STOP_SPEAKING (it lives here so loop.py can import the routes).
STOP_SPEAKING = {"stop", "jarvis stop", "stop jarvis", "be quiet", "thamb", "थांब", "थांबा"}
WAIT_WORDS = {"wait", "wait jarvis", "jarvis wait", "hold on", "one moment", "थांब जरा", "जरा थांब", "थांब जार्विस"}
STOP_WORDS = STOP_SPEAKING | WAIT_WORDS

_REMEMBER = (
    re.compile(r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?(?:please )?remember (?:that |this[:,]? )?(?P<text>.+?)[.!]?$", re.I),
    re.compile(r"^(?:जार्विस[, ]+)?(?:हे |ही |हा )?लक्षात ठेव(?:a|ा)?[:,]?\s+(?P<text>.+?)[.!]?$"),
    re.compile(r"^(?:जार्विस[, ]+)?(?P<text>.+?)\s*(?:हे |ही |हा )?लक्षात ठेव(?:a|ा)?[.!]?$"),
    re.compile(r"^(?:jarvis[, ]+)?(?P<text>.+?)\s+lakshat thev(?:a)?[.!]?$", re.I),
)
_SHOW_LAST = (
    re.compile(r"^(?:(?:hey |ok |okay )?jarvis[, ]+)?(?:show me |show |read me |read |open )?(?:the )?(?:last|latest|newest|previous) teardown(?: note)?[.!?]*$", re.I),
    re.compile(r"^(?:जार्विस[, ]+)?(?:शेवटचं|शेवटचे|शेवटचा|मागचं|मागचे|मागचा|शेवटचा|अखेरचं) teardown (?:दाखव|दाखवा|वाच|वाचा|सांग|सांगा)[.!?]*$"),
)


@dataclass(frozen=True)
class VoiceRoute:
    name: str
    patterns: tuple[str, ...]                              # for the record: what the route listens for
    action: Callable[[str], dict[str, Any] | None]         # text -> args when it matches, else None


def _stop(text: str) -> dict[str, Any] | None:
    return {} if normalize(text) in STOP_WORDS else None


def _remember(text: str) -> dict[str, Any] | None:
    t = " ".join(text.split())
    for pat in _REMEMBER:
        m = pat.match(t)
        if m and m.group("text").strip():
            return {"text": m.group("text").strip()}
    return None


def _show_last(text: str) -> dict[str, Any] | None:
    t = " ".join(text.split())
    return {} if any(p.match(t) for p in _SHOW_LAST) else None


def _teardown(text: str) -> dict[str, Any] | None:
    hit = teardown_intent(text)
    if hit is None:
        return None
    return {"url": hit[0], "question": hit[1]}


ROUTES: tuple[VoiceRoute, ...] = (
    VoiceRoute("stop", ("stop", "wait", "थांब"), _stop),
    VoiceRoute("remember", ("remember that ...", "लक्षात ठेव ..."), _remember),
    VoiceRoute("show_last_teardown", ("show me the last teardown", "शेवटचं teardown दाखव"), _show_last),
    VoiceRoute("teardown", ("reverse engineer X", "tear down X", "how does X do that", "what is X built with",
                            "X कसं बनवलंय", "X चं teardown कर"), _teardown),
)


def match_voice_route(text: str) -> tuple[VoiceRoute, dict[str, Any]] | None:
    """The first route whose action accepts the sentence, with its arguments."""
    if not text or not text.strip():
        return None
    for route in ROUTES:
        args = route.action(text)
        if args is not None:
            return route, args
    return None
