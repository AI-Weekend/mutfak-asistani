"""Yerel çalıştırma yardımcısı: TLS (truststore) + XAI anahtarını yükleyip bir modülü çalıştırır.

  uv run python scripts/local.py evals.run_eval --local
  uv run python scripts/local.py scripts.smoke

Anahtar ortamda yoksa MUTFAK_LOCAL_ENV_FILE=<.env yolu> ile yüklenir; yazdırılmaz. Bulutta/CI'da kullanılmaz (orada anahtarlar ortamdan gelir).
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import local_env  # noqa: E402

if not local_env.setup():
    sys.exit("XAI_API_KEY bulunamadı (ortamda ya da MUTFAK_LOCAL_ENV_FILE ile gösterilen .env içinde).")

module = sys.argv[1]
sys.argv = [module, *sys.argv[2:]]
runpy.run_module(module, run_name="__main__")
