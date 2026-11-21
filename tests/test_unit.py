"""Ağ çağrısı yapmayan testler: hane kuralları, retriever (sahte/keyword embedding),
araçlar (InMemoryStore), guard. Gerçek grok testleri test_live.py'de."""

from __future__ import annotations

import os

os.environ.setdefault("XAI_API_KEY", "test-key-yalnizca-import-icin")

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore

from langchain_core.messages import HumanMessage

from mutfak_asistani import household
from mutfak_asistani.graph import guard, menu_son_kontrol
from mutfak_asistani.ingestion import load_recipes
from mutfak_asistani.retriever import KeywordEmbeddings, RecipeStore
from mutfak_asistani.tools import append_list, calculator, edit_list, read_list


@pytest.fixture(scope="module")
def recipes():
    return {d.metadata["recipe"]: d for d in load_recipes()}


def test_ingestion_one_doc_per_recipe_with_metadata(recipes):
    assert set(recipes) == {
        "Fıstıklı Sütlaç",
        "Ispanaklı Peynirli Börek",
        "Mercimek Çorbası",
        "Nohutlu Susamlı Salata",
    }
    assert "Antep fıstığı" in recipes["Fıstıklı Sütlaç"].metadata["alerjen"]
    assert recipes["Fıstıklı Sütlaç"].metadata["source"].endswith(".pdf")


def test_retriever_keyword_fallback(recipes):
    store = RecipeStore(list(recipes.values()), KeywordEmbeddings(), "keyword-fallback")
    assert store.search("kırmızı mercimek çorbası", 1)[0].metadata["recipe"] == "Mercimek Çorbası"
    assert store.search("fıstıklı sütlaç", 1)[0].metadata["recipe"] == "Fıstıklı Sütlaç"
    assert store.search("börek", 1)[0].metadata["recipe"] == "Ispanaklı Peynirli Börek"


def test_allergen_pistachio_flags_elif(recipes):
    d = recipes["Fıstıklı Sütlaç"]
    rep = household.check_recipe(d.metadata["recipe"], d.page_content)
    assert not rep.safe_for_elif
    assert "Elif" in rep.as_text()


def test_allergen_sesame_and_mustard_not_flagged(recipes):
    d = recipes["Nohutlu Susamlı Salata"]
    rep = household.check_recipe(d.metadata["recipe"], d.page_content)
    assert rep.safe_for_elif and not rep.flags  # susam/hardal evde sorun değil


def test_allergen_borek_counts_as_hamur_isi(recipes):
    d = recipes["Ispanaklı Peynirli Börek"]
    rep = household.check_recipe(d.metadata["recipe"], d.page_content)
    assert rep.safe_for_elif and rep.counts_as_hamur_isi
    assert "en fazla bir" in rep.as_text()


def test_lentil_soup_is_clean(recipes):
    d = recipes["Mercimek Çorbası"]
    assert household.check_recipe(d.metadata["recipe"], d.page_content).flags == []


def test_menu_rules():
    assert household.check_menu(["Mercimek çorbası", "Nohutlu salata"]) == []
    assert household.check_menu(["Ispanaklı börek", "Su böreği"])  # 2 hamur işi
    assert household.check_menu(["Fıstıklı sütlaç"])  # fıstık
    assert household.check_menu(["Fıstıksız sütlaç"]) == []


def test_calculator():
    assert calculator.invoke({"expression": "1500 / 4"}) == "375.0"
    assert "Hesaplanamadı" in calculator.invoke({"expression": "__import__('os')"})


def _tool_graph(store):
    g = StateGraph(MessagesState)
    g.add_node("tools", ToolNode([read_list, append_list, edit_list]))
    g.add_edge(START, "tools")
    return g.compile(store=store)


def _call(graph, name, args, thread="t-ayse", **configurable):
    msg = AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"c-{name}", "type": "tool_call"}])
    out = graph.invoke({"messages": [msg]}, {"configurable": {"thread_id": thread, **configurable}})
    return out["messages"][-1].content


def test_shopping_list_store_roundtrip_across_calls():
    store = InMemoryStore()
    g = _tool_graph(store)
    assert "boş" in _call(g, "read_list", {})
    assert _call(g, "append_list", {"item": "süt"}) == "Eklendi: süt"
    _call(g, "append_list", {"item": "yumurta"})
    text = _call(g, "read_list", {})
    assert text.count("## Alınacaklar") == 1 and "- süt" in text and "- yumurta" in text
    _call(g, "edit_list", {"old": "- süt", "new": "- süt (2 litre)"})
    assert "- süt (2 litre)" in _call(g, "read_list", {})
    # başka thread'in listesi ayrı namespace'te
    assert "boş" in _call(g, "read_list", {}, thread="t-mehmet")


def test_guard_rejects_long_input():
    out = guard({"messages": [HumanMessage("x" * 1001)], "route": ""})
    assert out["route"] == "reddedildi" and "kısalt" in out["messages"][0].content
    assert guard({"messages": [HumanMessage("merhaba")], "route": ""})["route"] == ""


def test_web_search_degrades_without_key(monkeypatch):
    from mutfak_asistani.tools import web_search

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert "kapalı" in web_search.invoke({"query": "mevsim sebzesi"})


def test_parallel_appends_do_not_lose_updates():
    """Regresyon koruması: model birden çok append_list'i aynı turda paralel çağırır.

    Dürüst not: InMemoryStore + GIL ile bu testte yarış kilitsiz de tetiklenmiyor; kayıp güncelleme
    `langgraph dev` sunucusunda (async store köprüsü) bir kez gözlendi, kilitle 3/3 tur temiz geçti.
    """
    store = InMemoryStore()
    g = _tool_graph(store)
    items = [f"madde{i}" for i in range(12)]
    calls = [{"name": "append_list", "args": {"item": it}, "id": f"c{i}", "type": "tool_call"} for i, it in enumerate(items)]
    g.invoke({"messages": [AIMessage("", tool_calls=calls)]}, {"configurable": {"thread_id": "paralel"}})
    text = store.get(("alisveris", "paralel"), "liste").value["text"]
    assert all(f"- {it}\n" in text for it in items), text


def test_menu_post_check_flags_two_boreks_and_pistachio():
    temiz = "- **Pazartesi:** Mercimek çorbası\n- **Cumartesi:** Ispanaklı Peynirli Börek\nToplam: 400 TL"
    assert "uygun" in menu_son_kontrol(temiz)
    kotu = "- **Cuma:** Ispanaklı börek\n- **Cumartesi:** Su böreği\n- **Pazar:** Fıstıklı sütlaç"
    out = menu_son_kontrol(kotu)
    assert "sorun buldu" in out and "hamur işi" in out and "fıstık" in out
    assert menu_son_kontrol("Merhaba, menü şöyle olabilir.") == ""


# --- Store namespace kuralları (herkes tek proxy/anahtarla gelse de listeler karışmamalı) ---
def _ns_of(monkeypatch=None, **configurable):
    store = InMemoryStore()
    _call(_tool_graph(store), "append_list", {"item": "x"}, **configurable)
    return [ns for ns in store.list_namespaces() if ns and ns[0] == "alisveris"][0]


def test_namespace_defaults_to_thread_and_ignores_client_user_id(monkeypatch):
    monkeypatch.delenv("MUTFAK_TRUST_USER_ID", raising=False)
    # istemci user_id göndererek başkasının listesine erişemez
    assert _ns_of(thread="t1", user_id="kurban") == ("alisveris", "t1")


def test_namespace_trusts_user_id_only_with_env_flag(monkeypatch):
    monkeypatch.setenv("MUTFAK_TRUST_USER_ID", "1")
    assert _ns_of(thread="t1", user_id="ayse") == ("alisveris", "ayse")


@pytest.mark.parametrize("auth_id", ["anon:abc123", "user:42"])
def test_namespace_uses_auth_user_id_only_with_custom_auth_prefix(monkeypatch, auth_id):
    monkeypatch.delenv("MUTFAK_TRUST_USER_ID", raising=False)
    assert _ns_of(thread="t1", langgraph_auth_user_id=auth_id) == ("alisveris", auth_id)


@pytest.mark.parametrize("proxy_id", ["", None, "ls-api-key-owner", "shared-proxy"])
def test_namespace_ignores_shared_proxy_auth_id(monkeypatch, proxy_id):
    """Tek proxy + tek LangSmith anahtarı: auth id herkes için aynı/boş → thread'e düş."""
    monkeypatch.delenv("MUTFAK_TRUST_USER_ID", raising=False)
    assert _ns_of(thread="t-ziyaretci-1", langgraph_auth_user_id=proxy_id) == ("alisveris", "t-ziyaretci-1")
    assert _ns_of(thread="t-ziyaretci-2", langgraph_auth_user_id=proxy_id) == ("alisveris", "t-ziyaretci-2")


def test_namespace_fallback_without_thread_id():
    store = InMemoryStore()
    msg = AIMessage("", tool_calls=[{"name": "append_list", "args": {"item": "x"}, "id": "c", "type": "tool_call"}])
    _tool_graph(store).invoke({"messages": [msg]}, {"configurable": {}})
    assert store.get(("alisveris", "varsayilan"), "liste") is not None
