"""LLM-as-judge: 06-izleme.json'daki 'Hakem' rubriği (1–5, ev alerji kuralı).

İki kullanım:
  * yerel: `judge_answer(soru, cevap)` → (puan, gerekçe)
  * LangSmith: `langsmith_judge_evaluator` → `langsmith.evaluate(..., evaluators=[...])` ile uyumlu
"""

from __future__ import annotations

import re

from langchain_xai import ChatXAI

from mutfak_asistani.config import MODEL_NAME, maybe_inject_truststore
from mutfak_asistani.prompts import JUDGE_PROMPT

maybe_inject_truststore()


def parse_judgement(text: str) -> tuple[int | None, str]:
    """'Puan: 4\\nGerekçe: ...' → (4, '...'). Çözülemezse (None, ham metin)."""
    m = re.search(r"Puan:\s*([1-5])", text)
    r = re.search(r"Gerek[çc]e:\s*(.+)", text, flags=re.S)
    return (int(m.group(1)) if m else None, (r.group(1).strip() if r else text.strip()))


def _model() -> ChatXAI:
    return ChatXAI(model=MODEL_NAME, temperature=0, max_tokens=300, max_retries=2)


def judge_answer(soru: str, cevap: str) -> tuple[int | None, str]:
    msg = _model().invoke(JUDGE_PROMPT.format(soru=soru, cevap=cevap), config={"tags": ["node:judge", "course:ai-weekend-201"]})
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    return parse_judgement(text)


def langsmith_judge_evaluator(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
    """`langsmith.evaluate` evaluator'ı: puan 1–5 → score (0–1'e normalize) + yorum."""
    puan, gerekce = judge_answer(inputs["soru"], outputs["cevap"])
    return {
        "key": "ev_kurali_hakem",
        "score": None if puan is None else (puan - 1) / 4,
        "value": puan,
        "comment": gerekce,
    }
