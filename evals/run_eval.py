"""Offline değerlendirme: golden sorularını grafikten geçir, hakemle puanla.

  uv run python -m evals.run_eval --local        # LangSmith yok: puanları yazdır
  uv run python -m evals.run_eval                # langsmith.evaluate ile experiment oluştur

Offline eval = merge/deploy'dan ÖNCE golden set; online eval = deploy sonrası gerçek trafikteki
trace'leri örnekleyip aynı hakemle puanlamak (LangSmith online evaluator olarak aynı judge promptu bağlanır).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from mutfak_asistani.graph import build_graph

from .create_dataset import DATASET
from .golden import GOLDEN
from .judge import judge_answer, langsmith_judge_evaluator


def _target_factory():
    g = build_graph(checkpointer=InMemorySaver(), store=InMemoryStore())

    def target(inputs: dict) -> dict:
        r = g.invoke({"messages": [("user", inputs["soru"])]}, {"configurable": {"thread_id": str(uuid.uuid4())}})
        return {"cevap": r["messages"][-1].content, "rota": r["route"]}

    return target


def run_local() -> int:
    target = _target_factory()
    rows = []
    for ex in GOLDEN:
        out = target({"soru": ex["soru"]})
        puan, gerekce = judge_answer(ex["soru"], out["cevap"])
        rota_ok = out["rota"] == ex["beklenen_rota"]
        rows.append((ex, out, puan, gerekce, rota_ok))
        print(f"[{'OK ' if rota_ok else 'ROTA?'}] rota={out['rota']:<13} puan={puan} | {ex['soru'][:70]}")
        print(f"        gerekçe: {gerekce[:160]}")
    scored = [r[2] for r in rows if r[2] is not None]
    print(f"\nRota doğruluğu: {sum(r[4] for r in rows)}/{len(rows)}   Ortalama hakem puanı: {sum(scored) / max(len(scored), 1):.2f}")
    return 0


def run_langsmith() -> int:
    from langsmith import evaluate

    def rota_dogru(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        return {"key": "rota_dogru", "score": int(outputs["rota"] == reference_outputs["beklenen_rota"])}

    evaluate(
        _target_factory(),
        data=DATASET,
        evaluators=[langsmith_judge_evaluator, rota_dogru],
        experiment_prefix="mutfak-asistani",
        metadata={"course": "ai-weekend-201"},
        max_concurrency=2,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="LangSmith'siz çalıştır, puanları yazdır")
    args = ap.parse_args()
    if args.local or not os.getenv("LANGSMITH_API_KEY"):
        if not args.local:
            print("LANGSMITH_API_KEY yok → yerel moda geçildi.\n")
        return run_local()
    return run_langsmith()


if __name__ == "__main__":
    sys.exit(main())
