"""Yalnızca yerel testler için: XAI_API_KEY'i, MUTFAK_LOCAL_ENV_FILE ile gösterilen bir .env dosyasından yükler.

Anahtar asla yazdırılmaz ve projeye kopyalanmaz; yalnızca bu sürecin ortamına konur.
Dosya yoksa ya da ortamda zaten varsa hiçbir şey yapmaz.
"""

from __future__ import annotations

import os
from pathlib import Path




def load_xai_key() -> bool:
    if os.getenv("XAI_API_KEY"):
        return True
    env_file = os.getenv("MUTFAK_LOCAL_ENV_FILE")
    if env_file and Path(env_file).is_file():
        for line in Path(env_file).read_text().splitlines():
            if line.startswith("XAI_API_KEY="):
                os.environ["XAI_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
                return True
    return False


def setup() -> bool:
    """Yerel Mac için TLS + xAI anahtarı. Anahtar bulunduysa True."""
    os.environ.setdefault("MUTFAK_TRUSTSTORE", "1")
    from mutfak_asistani.config import maybe_inject_truststore

    maybe_inject_truststore()
    return load_xai_key()
