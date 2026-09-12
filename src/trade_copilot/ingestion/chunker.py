from __future__ import annotations

import re

from .loader import PageText

HEADING = re.compile(r"(?m)^(#{1,6}\s+.+|(?:\d+(?:\.\d+){0,4}|第[一二三四五六七八九十百]+[章节条])[^\n]{0,100})$")


def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_pages(pages: list[PageText], target_chars: int = 1600, overlap_chars: int = 220):
    """Yield page-aware chunks, preferring paragraph/heading boundaries."""
    current_section: str | None = None
    for page in pages:
        text = clean_text(page.text)
        if not text:
            continue
        pieces = re.split(r"\n\s*\n", text)
        buffer = ""
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if HEADING.match(piece) and len(piece) < 120:
                current_section = piece.lstrip("# ").strip()
            if buffer and len(buffer) + len(piece) + 2 > target_chars:
                yield page.page, current_section, buffer.strip()
                buffer = buffer[-overlap_chars:] + "\n\n" + piece
            else:
                buffer = f"{buffer}\n\n{piece}" if buffer else piece
        if buffer:
            yield page.page, current_section, buffer.strip()

