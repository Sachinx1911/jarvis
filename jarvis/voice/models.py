"""Local voice model files besides Whisper: what they are, where they live, how setup fetches them.

Everything goes under JARVIS_HOME/data/models/ (personal, git-ignored), never into the repo.
Nothing here downloads on import or when an engine loads: only `jarvis voice setup` calls
download(), after it has shown the size and Sachin said yes. Hugging Face downloads are pinned to
a repository commit, and large files are checked against their SHA-256 before they are used.

Sizes, commits and hashes were read from the Hugging Face API on 2026-10-10.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str = ""    # checked after download when set (large files)
    repo: str = ""      # "" = the model's repo
    revision: str = ""  # "" = the model's revision


@dataclass(frozen=True)
class VoiceModel:
    key: str               # the name used in config and in `jarvis voice setup --model <key>`
    title: str
    folder: str            # under data/models/
    repo: str              # Hugging Face repo ("" = not on Hugging Face)
    revision: str          # pinned commit
    files: tuple[ModelFile, ...]
    mb: int                # download size
    license: str
    ready_file: str        # the file whose presence means "ready to use"

    def path(self, home: Path) -> Path:
        return home / "data" / "models" / self.folder

    def present(self, home: Path) -> bool:
        return (self.path(home) / self.ready_file).is_file()


# Marathi speech-to-text. AI4Bharat IndicConformer for Marathi (NeMo hybrid CTC/RNN-T "large",
# MIT). The official repo (ai4bharat/indicconformer_stt_mr_hybrid_ctc_rnnt_large, .nemo, 523 MB)
# is gated behind a Hugging Face login. OpenVoiceOS publishes the same weights exported to ONNX
# (CTC branch) for the onnx-asr library, ungated, MIT; Jarvis uses its int8 file (138 MB).
INDICCONFORMER_MR = VoiceModel(
    key="indicconformer-mr",
    title="Marathi speech-to-text: AI4Bharat IndicConformer (ONNX int8)",
    folder="indicconformer/mr",
    repo="OpenVoiceOS/ai4bharat-indicconformer-mr-onnx",
    revision="b738dbf822f12c57ae8d9ea46c9fa9a52f977060",
    files=(ModelFile("config.json"), ModelFile("vocab.txt"),
           ModelFile("model.int8.onnx", "df2d4fb0af1a2b395e6f21f6536c5dfd6510e7db9b567b634f0bc0b412d34c93")),
    mb=138,
    license="MIT (AI4Bharat)",
    ready_file="model.int8.onnx",
)

# Offline Marathi voice. Meta MMS-TTS Marathi (VITS, 36M parameters). License CC-BY-NC 4.0:
# non-commercial use only, which covers Sachin's personal assistant. The tokenizer files come from
# the official repo. The weights come as an ONNX export of that same model (naklitechie, for
# transformers.js; CC-BY-NC 4.0 inherited), so speaking needs only onnxruntime + numpy, no torch.
# Checked 2026-10-10: its weights match the official model.safetensors (see TESTING.md, voice).
MMS_TTS_MAR = VoiceModel(
    key="mms-tts-mar",
    title="Marathi voice (offline): Meta MMS-TTS Marathi (ONNX)",
    folder="mms-tts/mar",
    repo="facebook/mms-tts-mar",
    revision="7af4a6db1df2eb20042d24cc7c180a492df1cc13",
    files=(ModelFile("config.json"), ModelFile("vocab.json"), ModelFile("tokenizer_config.json"),
           ModelFile("model.onnx", "cacb3ef44b7b2786d9ad993e31516e176bcb3d63f6a9fc265f04b1a97fa4c44c",
                     repo="naklitechie/mms-tts-mr-ONNX", revision="96e4d4ed1f379ea1205aac504423b1b4ab6ebe95")),
    mb=115,
    license="CC-BY-NC-4.0 (non-commercial; personal use is fine)",
    ready_file="model.onnx",
)

# Wake word. openWakeWord "hey_jarvis" plus its two feature models, from the project's GitHub
# release (openwakeword.utils.download_models). Pre-trained models: CC BY-NC-SA 4.0.
HEY_JARVIS = VoiceModel(
    key="hey_jarvis",
    title='Wake word: openWakeWord "hey_jarvis"',
    folder="openwakeword",
    repo="",
    revision="v0.5.1",
    files=(),
    mb=9,
    license="CC BY-NC-SA 4.0 (non-commercial; personal use is fine)",
    ready_file="hey_jarvis_v0.1.onnx",
)

VOICE_MODELS: dict[str, VoiceModel] = {m.key: m for m in (INDICCONFORMER_MR, MMS_TTS_MAR, HEY_JARVIS)}


class ChecksumError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


FileFetcher = Callable[[str, str, str, Path], Path]  # (repo, filename, revision, dest_dir) -> local path


def _hf_fetch(repo: str, filename: str, revision: str, dest_dir: Path) -> Path:
    # hf-xet transfers stalled at 0 bytes on this Mac (2026-10-10); plain HTTPS is reliable.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import hf_hub_download  # installed with faster-whisper

    return Path(hf_hub_download(repo, filename, revision=revision, local_dir=str(dest_dir)))


def download(model: VoiceModel, home: Path, fetch: FileFetcher | None = None) -> Path:
    """Fetch a Hugging Face model's files into data/models/<folder>/ and verify the hashes."""
    if not model.repo:
        raise ValueError(f"{model.key} is not downloaded from Hugging Face")
    dest = model.path(home)
    dest.mkdir(parents=True, exist_ok=True)
    for f in model.files:
        target = dest / f.name
        if target.is_file() and (not f.sha256 or sha256_of(target) == f.sha256):
            continue
        repo = f.repo or model.repo
        local = (fetch or _hf_fetch)(repo, f.name, f.revision or model.revision, dest)
        if f.sha256 and sha256_of(local) != f.sha256:
            local.unlink(missing_ok=True)
            raise ChecksumError(f"{f.name} from {repo} does not match its pinned SHA-256; deleted it")
    return dest
