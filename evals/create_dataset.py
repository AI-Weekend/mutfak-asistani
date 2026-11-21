"""LangSmith'te 'mutfak-asistani-golden' dataset'ini oluşturur (idempotent).

Kullanım:  uv run python -m evals.create_dataset
Gereken:   LANGSMITH_API_KEY
"""

from __future__ import annotations

import os
import sys

from langsmith import Client

from .golden import GOLDEN

DATASET = "mutfak-asistani-golden"


def main() -> int:
    if not os.getenv("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY yok; dataset oluşturulamadı (yerel mod için: python -m evals.run_eval --local).")
        return 1
    client = Client()
    if client.has_dataset(dataset_name=DATASET):
        print(f"'{DATASET}' zaten var; dokunulmadı.")
        return 0
    ds = client.create_dataset(DATASET, description="Mutfak asistanı golden seti: rota + ev kuralı tuzakları (AI Weekend 201)")
    client.create_examples(
        dataset_id=ds.id,
        inputs=[{"soru": g["soru"]} for g in GOLDEN],
        outputs=[{"beklenen_rota": g["beklenen_rota"], "ev_kurali": g["ev_kurali"]} for g in GOLDEN],
    )
    print(f"'{DATASET}' oluşturuldu: {len(GOLDEN)} örnek.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
