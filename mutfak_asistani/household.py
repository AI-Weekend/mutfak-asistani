"""Hane kuralları: data/notlar/alisveris.md notlarından türetilen sabit kurallar.

Langflow'da bu bilgi `alisveris.md` dosyasındaydı ve ajan okuyordu. Burada iki
şey yapıyoruz: (1) notları ham metin olarak sunuyoruz (haftalık menü promptu),
(2) alerjen kontrolü gibi güvenlik kritik kuralları deterministik koda alıyoruz —
çünkü "yer fıstığı" gibi bir kuralı LLM'in insafına bırakmak istemeyiz.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .config import data_dir

WEEKLY_BUDGET_TL = 1500
MAX_HAMUR_ISI_PER_WEEK = 1

# Elif için yasaklı malzeme kökleri (normalize edilmiş, küçük harf, aksansız)
ELIF_ALLERJENLERI = {
    "yer fistigi": ("yer fistigi", "fistik ezmesi", "fistik yagi"),
    "antep fistigi": ("antep fistigi", "fistikli", "fistik"),
}
# "bore" kökü hem "börek" hem "böreği" yakalar (k→ğ yumuşaması)
HAMUR_ISI_ANAHTARLARI = ("bore", "yufka", "manti", "pogaca", "gozleme", "lahmacun", "pide")


def normalize(text: str) -> str:
    """Küçük harf + aksansız (Türkçe İ/ı dahil) — eşleştirme için."""
    text = text.replace("İ", "i").replace("I", "ı").lower()
    text = text.replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def household_notes() -> str:
    """alisveris.md'nin ham metni (promptlara konur)."""
    return (data_dir() / "notlar" / "alisveris.md").read_text(encoding="utf-8")


@dataclass
class AllergenReport:
    recipe: str
    flags: list[str] = field(default_factory=list)  # kural ihlalleri / uyarılar
    safe_for_elif: bool = True
    counts_as_hamur_isi: bool = False

    def as_text(self) -> str:
        if not self.flags:
            return f"{self.recipe}: evin kurallarına göre sorun yok."
        return f"{self.recipe}: " + " ".join(self.flags)


def _alerjen_section(recipe_text: str) -> str:
    m = re.search(r"Alerjen bilgisi(.*?)(?:\nNot\b|\Z)", recipe_text, flags=re.S)
    return m.group(1) if m else ""


def check_recipe(recipe_name: str, recipe_text: str) -> AllergenReport:
    """Tarifin 'Alerjen bilgisi' bölümünü (ve malzemeleri) hane notlarıyla karşılaştırır.

    - Elif: yer fıstığı / Antep fıstığı → uyarı, güvenli değil.
    - Baba: gluten / börek-hamur işi → "haftada en fazla bir" notu.
    - Susam / hardal: evde herkes yiyebilir → uyarı yok.
    """
    report = AllergenReport(recipe=recipe_name)
    section = normalize(_alerjen_section(recipe_text))
    full = normalize(recipe_text)

    # Yalnızca OLUMLU eşleşmeler: malzeme listesi ve "İçerir:" cümlesi.
    # ("Yer fıstığı / sert kabuklu yemiş: yok" gibi olumsuz ifadeler sayılmaz.)
    contains_line = re.search(r"icerir:(.*?)(?:\.|$)", section, flags=re.S)
    contains = contains_line.group(1) if contains_line else ""
    ing = re.search(r"malzemeler(.*?)yapilisi", full, flags=re.S)
    ingredients = ing.group(1) if ing else ""
    nut_words = ("antep fistigi", "yer fistigi", "fistik")
    ingredient_hit = any(w in ingredients for w in nut_words)
    allergen_hit = any(w in contains for w in nut_words) or "sert kabuklu yemis" in contains
    if ingredient_hit or allergen_hit:
        report.safe_for_elif = False
        report.flags.append(
            "UYARI: Elif'in yer fıstığı/Antep fıstığı alerjisi var — bu tarif fıstık içeriyor; "
            "fıstıksız servis edin (tarifte önerilen: tarçın ya da hindistan cevizi) ve çapraz bulaşmaya dikkat."
        )

    glutenli = "gluten" in contains and "gluten: yok" not in section
    if glutenli or any(k in normalize(recipe_name) for k in HAMUR_ISI_ANAHTARLARI):
        report.counts_as_hamur_isi = "borek" in normalize(recipe_name) or "yufka" in full
        report.flags.append(
            "NOT: Babam gluteni azaltıyor — haftada en fazla bir börek/hamur işi; bu tarif glutenli."
        )
    return report


def check_menu(items: list[str]) -> list[str]:
    """Haftalık menü maddeleri için kural ihlallerini listeler (boş liste = temiz)."""
    problems: list[str] = []
    hamur = [i for i in items if any(k in normalize(i) for k in HAMUR_ISI_ANAHTARLARI)]
    if len(hamur) > MAX_HAMUR_ISI_PER_WEEK:
        problems.append(
            f"{len(hamur)} börek/hamur işi var ({', '.join(hamur)}); en fazla {MAX_HAMUR_ISI_PER_WEEK} olmalı."
        )
    for i in items:
        n = normalize(i)
        if "fistik" in n and "fistiksiz" not in n:
            problems.append(f"'{i}' fıstık içeriyor; Elif için uygun değil (yer fıstığı/Antep fıstığı alerjisi).")
    return problems
