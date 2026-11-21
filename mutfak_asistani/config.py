"""Ortam, model fabrikası ve sabitler.

Burada dış servis anahtarı okunur ama asla yazdırılmaz.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from langchain_xai import ChatXAI

COURSE = "ai-weekend-201"
PROJECT = "mutfak-asistani"
MODEL_NAME = os.getenv("MUTFAK_MODEL", "grok-4.3")

# --- Korumalar (guards) -------------------------------------------------
MAX_INPUT_CHARS = 1000  # bundan uzun kullanıcı mesajı kibarca reddedilir
ROUTER_MAX_TOKENS = 200
ANSWER_MAX_TOKENS = 1200  # tarif / ajan cevapları
AGENT_RECURSION_LIMIT = 12  # ajan başına en fazla ~5 araç turu
TAVILY_MAX_RESULTS = 3  # Langflow: max_results=3
HISTORY_MESSAGES = 8  # {gecmis} için son N mesaj


def maybe_inject_truststore() -> None:
    """Kurumsal TLS denetimi olan yerel makinede sistem sertifika deposunu kullan.

    Bulutta etkilenmesin diye yalnızca MUTFAK_TRUSTSTORE=1 iken çalışır.
    """
    if os.getenv("MUTFAK_TRUSTSTORE") != "1":
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # pragma: no cover - truststore yoksa sessizce geç
        pass


maybe_inject_truststore()


def data_dir() -> Path:
    """Paketlenmiş veri klasörü (PDF'ler + notlar)."""
    candidates = [
        os.getenv("MUTFAK_DATA_DIR"),
        Path(__file__).resolve().parent.parent / "data",
        Path(__file__).resolve().parent / "_data",
    ]
    for c in candidates:
        if c and Path(c).is_dir():
            return Path(c)
    raise FileNotFoundError("data/ klasörü bulunamadı (MUTFAK_DATA_DIR ayarlayın)")


def node_config(node: str, **extra: object) -> dict:
    """Her node için tag + metadata: LangSmith'te node'a göre süzülebilsin."""
    return {
        "tags": [f"course:{COURSE}", f"node:{node}"],
        "metadata": {"course": COURSE, "node": node, **extra},
    }


@lru_cache(maxsize=8)
def get_chat_model(node: str, max_tokens: int = ANSWER_MAX_TOKENS):
    """xAI grok sohbet modeli; düşük sıcaklık, sınırlı çıktı, node tag'li."""
    model = ChatXAI(
        model=MODEL_NAME,
        temperature=0.2,
        max_tokens=max_tokens,
        max_retries=2,
        timeout=60,
    )
    return model.with_config(node_config(node))
