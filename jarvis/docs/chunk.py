"""Split extracted blocks into search chunks that never cross a page or section.

Chunks are cut at paragraph, then sentence, then word boundaries, with a small
overlap so a fact split across two chunks is still found. Keeping each chunk inside
one page means every search hit has an exact citation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.docs.extract import Block

DEFAULT_CHARS = 900
DEFAULT_OVERLAP = 150


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    page: int | None
    section: str


def _pieces(text: str, size: int) -> list[str]:
    """Paragraphs, with over-long paragraphs split into sentences, then words."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            out.append(para)
            continue
        for sent in re.split(r"(?<=[.!?।])\s+", para):
            while len(sent) > size:
                cut = sent.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                out.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if sent:
                out.append(sent)
    return out


def chunk_blocks(blocks: list[Block], size: int = DEFAULT_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    for block in blocks:
        current = ""
        for piece in _pieces(block.text, size):
            if current and len(current) + 2 + len(piece) > size:
                chunks.append(Chunk(len(chunks), current, block.page, block.section))
                tail = current[-overlap:] if overlap else ""
                if tail and " " in tail:
                    tail = tail[tail.index(" ") + 1:]  # start the overlap on a word
                current = (tail + "\n\n" + piece) if tail else piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
        if current.strip():
            chunks.append(Chunk(len(chunks), current, block.page, block.section))
    return chunks
