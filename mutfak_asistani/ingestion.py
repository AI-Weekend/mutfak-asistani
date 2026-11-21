"""Tarif defteri ingestion: PDF → tarif başına bir Document.

Langflow karşılığı: File → Split Text → Knowledge (yaz). Burada tarif PDF'leri
zaten tek sayfalık olduğundan "tarife göre böl" = PDF başına bir parça; tarif adı
ve 'Alerjen bilgisi' metadata'da tutulur (cevap tarifi anabilsin, alerjen kontrolü
metin aramadan yapılabilsin).
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.documents import Document
from pypdf import PdfReader

from .config import data_dir


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_recipe_pdf(path: Path) -> Document:
    reader = PdfReader(str(path))
    text = _clean("\n".join(p.extract_text() or "" for p in reader.pages))
    lines = text.splitlines()
    name = lines[0].strip() if lines else path.stem
    m = re.search(r"Alerjen bilgisi\n(.*?)(?:\nNot\n|\Z)", text, flags=re.S)
    alerjen = " ".join(m.group(1).split()) if m else ""
    return Document(
        page_content=text,
        metadata={"recipe": name, "alerjen": alerjen, "source": path.name},
    )


def load_recipes(directory: Path | None = None) -> list[Document]:
    directory = directory or data_dir()
    pdfs = sorted(Path(directory).glob("*.pdf"))
    return [parse_recipe_pdf(p) for p in pdfs]
