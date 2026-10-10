"""`jarvis voice setup`: download the voice models, only when Sachin runs it, after showing the sizes.

Without --model it fetches what config/voice.yaml uses: the Whisper model, the Marathi
speech-to-text model (stt.marathi_engine), the offline Marathi voice (tts.marathi.offline_engine)
and the wake word (only when wake_word.enabled). `--model <name>` fetches one item: a Whisper
size (base, small, ...) or indicconformer-mr, mms-tts-mar, hey_jarvis.
Everything goes under JARVIS_HOME/data/models/ (personal, git-ignored).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from jarvis.control.audit import AuditLog
from jarvis.voice.models import HEY_JARVIS, INDICCONFORMER_MR, MMS_TTS_MAR, VOICE_MODELS, FileFetcher, VoiceModel
from jarvis.voice.models import download as download_hf
from jarvis.voice.stt import (
    ONNX_ASR_HINT,
    PACKAGE_HINT,
    WHISPER_MODELS,
    faster_whisper_installed,
    model_path,
    model_present,
    onnx_asr_installed,
)
from jarvis.voice.wakeword import PACKAGE_HINT as WAKEWORD_HINT
from jarvis.voice.wakeword import download_wakeword, openwakeword_installed

Downloader = Callable[[str, Path], None]
YES = ("y", "yes", "ho", "हो")


def _download(model: str, dest: Path) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # hf-xet stalled at 0 bytes on the Mac (2026-10-10)
    from faster_whisper import download_model

    dest.mkdir(parents=True, exist_ok=True)
    download_model(model, output_dir=str(dest))


@dataclass
class _Item:
    key: str
    title: str
    mb: int
    source: str
    dest: Path
    license: str
    present: Callable[[], bool]
    run: Callable[[], None]
    missing_package: str = ""   # install hint when a needed package is absent
    note: str = ""              # shown next to the item (e.g. a package needed later, to use it)


def _whisper_item(home: Path, model: str, downloader: Downloader | None, installed: Callable[[], bool]) -> _Item:
    repo, mb = WHISPER_MODELS[model]
    dest = model_path(home, model)
    return _Item(f"whisper-{model}", f"Speech-to-text model: Whisper {model!r}", mb,
                 f"https://huggingface.co/{repo}", dest, "MIT",
                 lambda: model_present(home, model), lambda: (downloader or _download)(model, dest),
                 "" if installed() else PACKAGE_HINT)


def _voice_item(home: Path, m: VoiceModel, fetch: FileFetcher | None,
                wake_downloader: Callable[[Path], Any] | None) -> _Item:
    if m is HEY_JARVIS:
        return _Item(m.key, m.title, m.mb, "https://github.com/dscripka/openWakeWord/releases (v0.5.1)",
                     m.path(home), m.license, lambda: m.present(home),
                     lambda: (wake_downloader or download_wakeword)(home),
                     "" if wake_downloader or openwakeword_installed() else WAKEWORD_HINT)
    sources = sorted({f.repo or m.repo for f in m.files})
    note = ""
    if m is INDICCONFORMER_MR and not onnx_asr_installed():
        note = f"to use it: {ONNX_ASR_HINT}"
    return _Item(m.key, m.title, m.mb, ", ".join(f"https://huggingface.co/{r}" for r in sources),
                 m.path(home), m.license, lambda: m.present(home), lambda: download_hf(m, home, fetch),
                 "" if fetch or faster_whisper_installed() else PACKAGE_HINT, note)


def plan(cfg: dict[str, Any], home: Path, model: str | None = None, downloader: Downloader | None = None,
         installed: Callable[[], bool] = faster_whisper_installed, fetch: FileFetcher | None = None,
         wake_downloader: Callable[[Path], Any] | None = None) -> list[_Item] | None:
    """The items to set up, or None for an unknown --model name."""
    if model:
        if model in WHISPER_MODELS:
            return [_whisper_item(home, model, downloader, installed)]
        if model in VOICE_MODELS:
            return [_voice_item(home, VOICE_MODELS[model], fetch, wake_downloader)]
        return None
    stt, tts, ww = cfg.get("stt", {}), cfg.get("tts", {}).get("marathi", {}), cfg.get("wake_word", {})
    items = [_whisper_item(home, stt.get("model", "small"), downloader, installed)]
    if (stt.get("marathi_engine") or "none").lower() == "indicconformer":
        items.append(_voice_item(home, INDICCONFORMER_MR, fetch, wake_downloader))
    if (tts.get("offline_engine") or "none").lower() == "mms_tts":
        items.append(_voice_item(home, MMS_TTS_MAR, fetch, wake_downloader))
    if ww.get("enabled", False):
        items.append(_voice_item(home, HEY_JARVIS, fetch, wake_downloader))
    return items


def _choices(out: TextIO) -> None:
    print("Choose one of:", file=out)
    for name, (repo, mb) in WHISPER_MODELS.items():
        print(f"  {name:<18} {mb:>5} MB  Whisper ({repo})", file=out)
    for m in VOICE_MODELS.values():
        print(f"  {m.key:<18} {m.mb:>5} MB  {m.title}", file=out)


def run_setup(cfg: dict[str, Any], home: Path, out: TextIO, inp: TextIO, model: str | None = None,
              assume_yes: bool = False, audit: AuditLog | None = None,
              downloader: Downloader | None = None, installed: Callable[[], bool] = faster_whisper_installed,
              fetch: FileFetcher | None = None, wake_downloader: Callable[[Path], Any] | None = None) -> int:
    items = plan(cfg, home, model, downloader, installed, fetch, wake_downloader)
    if items is None:
        print(f"Unknown model {model!r}.", file=out)
        _choices(out)
        return 2
    code = 0
    todo: list[_Item] = []
    for item in items:
        if item.present():
            print(f"{item.title}: already downloaded: {item.dest}", file=out)
        elif item.missing_package:
            print(f"{item.title}: a package is missing. First: {item.missing_package}", file=out)
            code = 1
        else:
            todo.append(item)
    if not todo:
        return code
    for item in todo:
        print(f"{item.title}, {item.mb} MB, from {item.source}", file=out)
        print(f"  license: {item.license}; saved to: {item.dest} (personal data folder, not in git)", file=out)
        if item.note:
            print(f"  {item.note}", file=out)
    total = sum(i.mb for i in todo)
    if not assume_yes:
        out.write(f"Download {total} MB now? [y/N] ")
        out.flush()
        if inp.readline().strip().lower() not in YES:
            print("Not downloaded.", file=out)
            return 1
    for item in todo:
        error = ""
        try:
            item.run()
        except Exception as e:  # network, disk or checksum problems: report, keep going
            error = f"{type(e).__name__}: {e}"
        ok = not error and item.present()
        if audit:
            audit.write("voice_setup", model=item.key, size_mb=item.mb, ok=ok, error=error[:200] or None)
        if ok:
            print(f"{item.title}: done.", file=out)
        else:
            print(f"{item.title}: download failed{f' ({error})' if error else ''}. Try again.", file=out)
            code = 1
    if code == 0:
        print("Done.", file=out)
    return code
