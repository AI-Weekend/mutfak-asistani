"""Tarif defteri retriever: bellek içi numpy vektör deposu.

LangSmith Deployment'ta dış veritabanı gerekmesin diye indeks başlangıçta,
pakete gömülü PDF'lerden (4 tarif) kurulur. Embedding değiştirilebilir:

* OPENAI_API_KEY varsa → OpenAI `text-embedding-3-small`
* yoksa → deterministik anahtar-kelime (hashing bag-of-words) yedeği.
  Testlerde ve anahtarsız yerel çalıştırmada kullanılır; üretimde OpenAI kullanın.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from .household import normalize
from .ingestion import load_recipes


class KeywordEmbeddings(Embeddings):
    """Anahtar-kelime yedeği: aksansız token'ların hash'lenmiş sayım vektörü.

    Gerçek anlam benzerliği vermez; ama "mercimek", "börek" gibi tarif adı ve
    malzeme eşleşmeleri için yeterlidir. Test ve anahtarsız çalışma içindir.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", normalize(text)):
            if len(tok) < 3:
                continue
            # kaba kök: son ekleri kırp ki "mercimekli" ≈ "mercimek"
            tok = tok[:6]
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return v.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def get_embeddings() -> tuple[Embeddings, str]:
    """(embedding, ad) — anahtar yoksa yedeğe düşer."""
    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model="text-embedding-3-small"), "openai:text-embedding-3-small"
    return KeywordEmbeddings(), "keyword-fallback"


class RecipeStore:
    """Küçük, bellek içi vektör deposu (kosinüs benzerliği)."""

    def __init__(self, docs: list[Document], embeddings: Embeddings, embeddings_name: str):
        self.docs = docs
        self.embeddings = embeddings
        self.embeddings_name = embeddings_name
        m = np.array(embeddings.embed_documents([d.page_content for d in docs]), dtype=np.float32)
        self._matrix = m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)

    def search(self, query: str, k: int = 3) -> list[Document]:
        q = np.array(self.embeddings.embed_query(query), dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm == 0:
            return []
        scores = self._matrix @ (q / norm)
        order = np.argsort(-scores)[:k]
        return [self.docs[i] for i in order if scores[i] > 0]


@lru_cache(maxsize=1)
def get_store() -> RecipeStore:
    emb, name = get_embeddings()
    return RecipeStore(load_recipes(), emb, name)


def format_recipes(docs: list[Document]) -> str:
    """{tarifler} için metin (Langflow Parser bileşeni karşılığı)."""
    if not docs:
        return "(tarif defterinde bu soruyla ilgili tarif bulunamadı)"
    return "\n\n---\n\n".join(f"[Tarif: {d.metadata['recipe']}]\n{d.page_content}" for d in docs)
