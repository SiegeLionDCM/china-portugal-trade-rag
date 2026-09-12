from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class PageText:
    page: int | None
    text: str


def load_document(path: Path) -> list[PageText]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            return [PageText(page=i + 1, text=page.get_text("text")) for i, page in enumerate(pdf)]
    if suffix in {".md", ".txt"}:
        return [PageText(page=None, text=path.read_text(encoding="utf-8"))]
    raise ValueError(f"Unsupported file type: {path.suffix}")
