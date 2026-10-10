"""Document uploads from the dashboard into projects/<name>/docs/.

- Only .md, .txt, .pdf and .docx, checked by extension AND content (PDF magic, DOCX zip
  magic, UTF-8 text).
- The file name is reduced to one safe component: no folders, no "..", no control or
  shell characters, no Windows device names. Letters of any script (Devanagari too) stay.
- The final path must resolve inside the project's docs folder (links cannot escape).
- Written to a temp file in the same folder, then moved into place. Existing files are
  kept unless the caller asks to replace them.
"""

from __future__ import annotations

import os
import tempfile
import unicodedata
from pathlib import Path

ALLOWED_EXT = {".md", ".txt", ".pdf", ".docx"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_NAME_CHARS = 120
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class UploadError(ValueError):
    pass


def safe_filename(raw: str) -> str:
    """One safe file name, or UploadError."""
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").split("/")[-1]  # drop any folder part
    out = []
    for ch in name:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N") or ch in " ._-()":
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip(" .")
    while ".." in name:
        name = name.replace("..", ".")
    if not name or name.startswith("."):
        raise UploadError("the file name has no usable letters")
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        raise UploadError("the file name needs an extension (.md, .txt, .pdf or .docx)")
    ext = "." + ext.lower()
    if ext not in ALLOWED_EXT:
        raise UploadError(f"only {', '.join(sorted(ALLOWED_EXT))} files can be added")
    if stem.split(".")[0].strip().lower() in _WINDOWS_DEVICES:
        stem = "_" + stem
    stem = stem[: MAX_NAME_CHARS - len(ext)].rstrip(" .")
    return stem + ext


def check_content(name: str, data: bytes, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    if not data:
        raise UploadError("the file is empty")
    if len(data) > max_bytes:
        raise UploadError(f"the file is larger than {max_bytes // (1024 * 1024)} MB")
    ext = Path(name).suffix.lower()
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise UploadError("this is not a PDF file")
    if ext == ".docx" and not data.startswith(b"PK\x03\x04"):
        raise UploadError("this is not a Word .docx file")
    if ext in (".md", ".txt"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise UploadError("text files must be UTF-8") from e
        if b"\x00" in data:
            raise UploadError("text files must not contain binary data")


def save_upload(docs_dir: Path, raw_name: str, data: bytes, replace: bool = False,
                max_bytes: int = MAX_UPLOAD_BYTES) -> Path:
    name = safe_filename(raw_name)
    check_content(name, data, max_bytes)
    docs_dir.mkdir(parents=True, exist_ok=True)
    root = docs_dir.resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise UploadError("the file must go directly into the project's docs folder")
    if target.exists() and not replace:
        raise FileExistsError(name)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise UploadError("cannot replace this path")
    fd, tmp = tempfile.mkstemp(prefix=".upload-", dir=root)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
