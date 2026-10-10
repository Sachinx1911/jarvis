"""`jarvis voice setup`: download the Whisper model, only when Sachin runs it, after showing the size."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TextIO

from jarvis.control.audit import AuditLog
from jarvis.voice.stt import (
    PACKAGE_HINT,
    WHISPER_MODELS,
    faster_whisper_installed,
    model_path,
    model_present,
)

Downloader = Callable[[str, Path], None]


def _download(model: str, dest: Path) -> None:
    from faster_whisper import download_model

    dest.mkdir(parents=True, exist_ok=True)
    download_model(model, output_dir=str(dest))


def run_setup(cfg: dict[str, Any], home: Path, out: TextIO, inp: TextIO, model: str | None = None,
              assume_yes: bool = False, audit: AuditLog | None = None,
              downloader: Downloader | None = None, installed: Callable[[], bool] = faster_whisper_installed) -> int:
    model = model or cfg.get("stt", {}).get("model", "small")
    if model not in WHISPER_MODELS:
        print(f"Unknown model {model!r}. Choose one of:", file=out)
        for name, (repo, mb) in WHISPER_MODELS.items():
            print(f"  {name:<15} {mb:>5} MB  ({repo})", file=out)
        return 2
    repo, mb = WHISPER_MODELS[model]
    dest = model_path(home, model)
    if model_present(home, model):
        print(f"Whisper model {model!r} is already downloaded: {dest}", file=out)
        return 0
    if not installed():
        print(f"faster-whisper is not installed. First: {PACKAGE_HINT}", file=out)
        return 1
    print(f"Speech-to-text model: Whisper {model!r}, {mb} MB, from https://huggingface.co/{repo}", file=out)
    print(f"Saved to: {dest} (personal data folder, not in git)", file=out)
    if not assume_yes:
        out.write(f"Download {mb} MB now? [y/N] ")
        out.flush()
        if inp.readline().strip().lower() not in ("y", "yes", "ho", "हो"):
            print("Not downloaded.", file=out)
            return 1
    (downloader or _download)(model, dest)
    ok = model_present(home, model)
    if audit:
        audit.write("voice_setup", model=model, size_mb=mb, ok=ok)
    print("Done." if ok else "Download finished, but model.bin is missing. Try again.", file=out)
    return 0 if ok else 1
