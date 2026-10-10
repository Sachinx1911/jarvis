"""Approvals in voice mode: Jarvis says what it wants to do; only an explicit yes allows it.

The full request (exact arguments) is shown on screen. The spoken summary always uses the
local voice (it is marked P2, so it never goes to a cloud voice). Sachin answers by typing
y / yes / ho, or presses Enter and says "yes" / "ho". Anything else, silence, a low-confidence
transcript or any error means no.
"""

from __future__ import annotations

import re
from typing import Any, TextIO

from jarvis.control.approvals import ApprovalRequest, Approver
from jarvis.control.audit import AuditLog
from jarvis.voice.base import VoiceUnavailable

TYPED_YES = {"y", "yes", "ho", "हो"}
SPOKEN_YES = {"yes", "yes please", "yes jarvis", "jarvis yes", "ho", "ho jarvis", "हो", "हो जार्विस"}


def normalize(text: str) -> str:
    text = re.sub(r"[^\w\sऀ-ॿ]", " ", text.lower())
    return " ".join(text.split())


def is_explicit_yes(text: str) -> bool:
    return normalize(text) in SPOKEN_YES


def spoken_summary(req: ApprovalRequest) -> str:
    return (f"Approval needed. I want to run {req.tool.replace('_', ' ')}, tier {req.tier}, because of a "
            f"{req.reason}. The details are on screen. Say yes or ho to allow. Anything else means no.")


def voice_approver(speech: Any, stt: Any, recorder: Any, out: TextIO, inp: TextIO, audit: AuditLog | None = None,
                   min_confidence: float = 0.45, language_hint: str | None = None) -> Approver:
    def ask(req: ApprovalRequest) -> bool:
        print("\n" + req.describe(), file=out)
        playback = None
        try:
            playback = speech.speak(spoken_summary(req), language="en", sensitivity="P2").playback
        except VoiceUnavailable:
            pass
        out.write("Allow? Type y / ho, or press Enter and say it. [default: no] ")
        out.flush()
        line = inp.readline()
        if playback is not None:
            playback.stop()
        answer, how, heard = False, "typed", ""
        if line.strip():
            answer = line.strip().lower() in TYPED_YES
        elif line:  # Enter: answer by voice
            how = "spoken"
            try:
                print("Listening... press Enter when done.", file=out)
                t = stt.transcribe(recorder.record_push_to_talk(), language_hint)
                heard = t.text
                answer = t.confidence >= min_confidence and is_explicit_yes(t.text)
                print(f"Heard: {t.text!r}", file=out)
            except Exception as e:  # no microphone, no model, anything: deny
                how = f"spoken (failed: {type(e).__name__})"
        print("Allowed." if answer else "Denied.", file=out)
        if audit:
            audit.write("voice_approval", tool=req.tool, tier=req.tier, answered=how, approved=answer,
                        heard_chars=len(heard))
        return answer

    return ask
