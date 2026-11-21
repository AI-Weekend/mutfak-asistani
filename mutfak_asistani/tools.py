"""Araçlar: hesap makinesi, Tavily, alışveriş listesi (Store), alerjen kontrolü, menü.

Langflow'daki MCP filesystem sunucusu (list_allowed_directories / read_file /
append_file / edit_file → notlar/alisveris.md) burada LangGraph **Store**'a taşındı:

    MCP dosyası alisveris.md  →  Store öğesi  namespace=("alisveris", <thread | auth kullanıcısı>), key="liste"

Araç adları MCP araçlarına yakın tutuldu: read_list ≈ read_file,
append_list ≈ append_file, edit_list ≈ edit_file.
"""

from __future__ import annotations

import ast
import operator
import os
import threading
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool

from . import household
from .config import TAVILY_MAX_RESULTS
from .retriever import format_recipes, get_store

# ---------------------------------------------------------------- hesap makinesi
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 10:
            raise ValueError("üs çok büyük")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("desteklenmeyen ifade")


@tool
def calculator(expression: str) -> str:
    """Aritmetik hesaplar (+ - * / ** %). Örn: '1500 / 4' ya da '250 * 6 / 4'.
    Miktar, porsiyon ve fiyat hesaplarında kafadan hesaplama yerine bunu kullan."""
    try:
        tree = ast.parse(expression.replace(",", ".").replace("×", "*"), mode="eval")
        result = _eval(tree.body)
    except Exception as e:  # noqa: BLE001
        return f"Hesaplanamadı: {e}"
    return str(round(result, 4))


# ---------------------------------------------------------------- web arama (Tavily)
@tool
def web_search(query: str) -> str:
    """Güncel bilgi için web araması (Tavily; en fazla 3 sonuç, basic derinlik).
    Mevsiminde ne var, güncel fiyat gibi sorularda bir kez kullan; kaynağı belirt."""
    if not os.getenv("TAVILY_API_KEY"):
        return "Web araması şu an kapalı (TAVILY_API_KEY tanımlı değil). Kendi bilginle, belirsizliği belirterek cevapla."
    try:
        from langchain_tavily import TavilySearch

        search = TavilySearch(max_results=min(TAVILY_MAX_RESULTS, 3), search_depth="basic")
        res: Any = search.invoke({"query": query})
    except Exception as e:  # noqa: BLE001
        return f"Web araması başarısız oldu ({type(e).__name__}). Kendi bilginle cevapla ve bunu belirt."
    results = res.get("results", []) if isinstance(res, dict) else []
    if not results:
        return "Web aramasında sonuç bulunamadı."
    return "\n\n".join(
        f"{r.get('title')} — {r.get('url')}\n{(r.get('content') or '')[:400]}" for r in results[:TAVILY_MAX_RESULTS]
    )


# ---------------------------------------------------------------- alışveriş listesi (Store)
LIST_KEY = "liste"
# Model "süt ve yumurta ekle" gibi isteklerde append_list'i PARALEL çağırabilir; Store'da
# compare-and-set olmadığı için oku-değiştir-yaz bölümü kilitlenir (kayıp güncelleme olmasın).
# Not: kilit süreç içidir; çok işçili dağıtımda aynı kullanıcıya eşzamanlı ayrı run'lar için
# Store'a sürüm alanı (optimistic concurrency) eklenmelidir — docs/design.md'ye bakın.
_LIST_LOCK = threading.Lock()
HEADING = "## Alınacaklar"


def _namespace(runtime: ToolRuntime) -> tuple[str, str]:
    """Liste kimin? Sırayla:

    1. ``langgraph_auth_user_id`` — YALNIZCA custom auth handler'ın verdiği ``anon:`` / ``user:``
       önekli kimlikler. (Herkes tek bir proxy + tek LangSmith anahtarıyla geliyorsa bu alan
       herkes için aynı/boş olur; önek kontrolü onu kullanıcı kimliği saymamızı engeller.)
    2. ``user_id`` — istemci kontrollü olduğu için yalnızca ``MUTFAK_TRUST_USER_ID=1`` ile (yerel test).
    3. ``thread_id`` — varsayılan: liste konuşma (thread) başınadır.
    4. ``"varsayilan"``.
    """
    cfg = (runtime.config or {}).get("configurable", {}) or {}
    auth_id = cfg.get("langgraph_auth_user_id")
    if isinstance(auth_id, str) and auth_id.startswith(("anon:", "user:")):
        who = auth_id
    elif os.getenv("MUTFAK_TRUST_USER_ID") == "1" and cfg.get("user_id"):
        who = cfg["user_id"]
    else:
        who = cfg.get("thread_id") or "varsayilan"
    return ("alisveris", str(who))


def _get(runtime: ToolRuntime) -> str:
    store = runtime.store
    if store is None:
        raise RuntimeError("Store yok: grafik bir store ile derlenmeli (langgraph dev bunu sağlar).")
    item = store.get(_namespace(runtime), LIST_KEY)
    return item.value["text"] if item else ""


def _put(runtime: ToolRuntime, text: str) -> None:
    runtime.store.put(_namespace(runtime), LIST_KEY, {"text": text})


@tool
def read_list(runtime: ToolRuntime) -> str:
    """Kullanıcının alışveriş listesini okur (MCP read_file karşılığı). Liste boşsa bunu söyler."""
    text = _get(runtime)
    return text if text.strip() else "(liste boş — henüz '## Alınacaklar' başlığı yok)"


@tool
def append_list(item: str, runtime: ToolRuntime) -> str:
    """Listeye madde ekler (MCP append_file karşılığı). '## Alınacaklar' başlığı yoksa
    başlığı da oluşturur; varsa maddeyi başlığın altına ekler. Diğer içeriğe dokunmaz."""
    item = item.strip().lstrip("-• ").strip()
    if not item:
        return "Boş madde eklenmedi."
    line = f"- {item}"
    with _LIST_LOCK:
        text = _get(runtime)
        if HEADING not in text:
            text = (text.rstrip() + "\n\n" if text.strip() else "") + f"{HEADING}\n{line}\n"
        else:
            text = text.rstrip() + f"\n{line}\n"
        _put(runtime, text)
    return f"Eklendi: {item}"


@tool
def edit_list(old: str, new: str, runtime: ToolRuntime) -> str:
    """Listedeki bir metni değiştirir (MCP edit_file karşılığı). `new` boşsa satır silinir.
    Örn. miktar güncellemek: old='- süt', new='- süt (2 litre)'."""
    with _LIST_LOCK:
        text = _get(runtime)
        if old not in text:
            return f"Listede '{old}' bulunamadı; önce read_list ile içeriğe bak."
        if new.strip():
            text = text.replace(old, new, 1)
        else:
            text = text.replace(old + "\n", "", 1).replace(old, "", 1)
        _put(runtime, text)
    return "Güncellendi."


# ---------------------------------------------------------------- tarif araması + alerjen
@tool
def tarif_ara(sorgu: str) -> str:
    """Tarif defterinde arar ve eşleşen tarifleri (malzeme, yapılış, alerjen bilgisi) döndürür."""
    return format_recipes(get_store().search(sorgu, k=3))


@tool
def alerjen_kontrol(tarif_adi: str) -> str:
    """Tarif defterindeki bir tarifin 'Alerjen bilgisi'ni evin notlarıyla karşılaştırır:
    Elif'in yer fıstığı/Antep fıstığı alerjisi ve babanın gluten/börek sınırı.
    `tarif_adi` kısmi olabilir (örn. 'sütlaç')."""
    wanted = household.normalize(tarif_adi)
    for d in get_store().docs:
        if wanted in household.normalize(d.metadata["recipe"]) or household.normalize(d.metadata["recipe"]) in wanted:
            return household.check_recipe(d.metadata["recipe"], d.page_content).as_text()
    return f"'{tarif_adi}' tarif defterinde yok; alerjen bilgisi doğrulanamadı."


@tool
def menu_kurallarini_dogrula(yemekler: list[str]) -> str:
    """Haftalık menüdeki yemek adlarını evin kurallarına göre denetler
    (en fazla 1 börek/hamur işi; fıstık yok). Sorun yoksa 'TEMİZ' döner."""
    problems = household.check_menu(yemekler)
    return "TEMİZ" if not problems else "SORUN: " + " ".join(problems)


def shopping_tools() -> list[BaseTool]:
    return [web_search, calculator, read_list, append_list, edit_list]


def nutrition_tools() -> list[BaseTool]:
    return [calculator, web_search]


def menu_tools() -> list[BaseTool]:
    return [tarif_ara, alerjen_kontrol, menu_kurallarini_dogrula, calculator]
