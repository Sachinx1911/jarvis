"""Voice (PLAN.md 14): push-to-talk, speech-to-text, text-to-speech, barge-in, wake word.

Every engine sits behind an interface in jarvis/voice/base.py so it can be swapped
(PLAN.md 5.8 migration rules). Engines with heavy dependencies import them lazily.
"""
