"""Gerçek grok çağrısı yapan testler (XAI_API_KEY gerekir; yoksa atlanır).

Not: OPENAI/TAVILY/LANGSMITH anahtarı yok → retriever 'keyword-fallback' ile, web arama kapalı çalışır.
Çıktılar scripts/smoke.py ile .coord/test-outputs.md'ye de kaydedilir.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

import local_env

pytestmark = pytest.mark.live

HAS_KEY = local_env.setup()
if not HAS_KEY:
    pytest.skip("XAI_API_KEY yok", allow_module_level=True)

from evals.judge import judge_answer  # noqa: E402
from mutfak_asistani.graph import build_graph  # noqa: E402


@pytest.fixture()
def app():
    store = InMemoryStore()
    return build_graph(checkpointer=InMemorySaver(), store=store), store


def ask(app, text, thread):
    return app.invoke({"messages": [("user", text)]}, {"configurable": {"thread_id": thread}})


@pytest.mark.parametrize(
    "soru,rota",
    [
        ("Elimde kırmızı mercimek ve havuç var, ne pişirebilirim?", "tarif"),
        ("Listeme süt ve yumurta ekler misin?", "alisveris"),
        ("Bir porsiyon mercimek çorbasının kalorisi ne kadar?", "beslenme"),
        ("Bana 1.500 TL'ye bir haftalık menü planla.", "haftalik_menu"),
        ("Bana Python'da bir sıralama algoritması yazar mısın?", "konu_disi"),
    ],
)
def test_routing(app, soru, rota):
    g, _ = app
    # Yalnızca yönlendirmeyi test et: router node'unu doğrudan çalıştır (cevap üretmeden)
    from mutfak_asistani.graph import router

    out = router({"messages": [HumanMessage(soru)], "route": ""}, {})
    assert out["route"] == rota


def test_rag_cites_recipe(app):
    g, _ = app
    r = ask(g, "Mercimek çorbasının alerjen bilgisi nedir?", str(uuid.uuid4()))
    assert r["route"] == "tarif"
    answer = r["messages"][-1].content
    assert "Mercimek Çorbası" in answer or "mercimek çorbası" in answer.lower()
    assert "süt" in answer.lower() or "tereyağı" in answer.lower()


def test_memory_gluten_excludes_borek(app):
    g, _ = app
    t = str(uuid.uuid4())
    ask(g, "Babam gluteni azaltıyor, bu hafta bizde börek ve hamur işi yok. Not al.", t)
    r = ask(g, "Elimde ıspanak ve peynir var, akşama ne yapayım?", t)
    answer = r["messages"][-1].content
    # Börek öneriliyor mu? Hakemle değil, doğrudan basit bir model sorusuyla kontrol et.
    from evals.judge import _model

    verdict = _model().invoke(
        "Aşağıdaki cevap ıspanaklı böreği ya da başka bir börek/hamur işini YAPILMASI İÇİN ÖNERİYOR mu? "
        "(Yalnızca 'uygun değil' diye elenmişse hayır say.) Tek kelime: EVET ya da HAYIR.\n\n" + answer
    ).content.strip().upper()
    assert verdict.startswith("HAYIR"), answer


def test_shopping_list_append_then_read_across_turns(app):
    g, store = app
    t = str(uuid.uuid4())
    r1 = ask(g, "Alışveriş listeme süt ve yumurta ekle.", t)
    assert r1["route"] == "alisveris"
    saved = store.get(("alisveris", t), "liste")  # liste thread başına
    assert saved is not None and "süt" in saved.value["text"].lower() and "yumurta" in saved.value["text"].lower()
    r2 = ask(g, "Listemde ne var?", t)
    assert "süt" in r2["messages"][-1].content.lower()
    # başka thread'in listesi boş
    assert store.get(("alisveris", "baska-thread"), "liste") is None


def test_judge_scores_pistachio_answer_low_and_safe_answer_high():
    soru = "Cumartesi Elif gelecek, tatlı olarak ne yapayım?"
    kotu = "Harika bir fikir: Fıstıklı Sütlaç yap! Üzerine bol Antep fıstığı serp, herkes bayılacak."
    iyi = (
        "Fıstıklı Sütlaç'ı fıstıksız yap: Elif'in yer fıstığı ve Antep fıstığı alerjisi var, "
        "üzerine fıstık yerine tarçın ya da hindistan cevizi serp ve çapraz bulaşmaya dikkat et."
    )
    guvenli = "Tatlı yerine Nohutlu Susamlı Salata ve mercimek çorbası yap; ikisi de fıstıksız, Elif için güvenli."
    p_kotu, _ = judge_answer(soru, kotu)
    p_iyi, _ = judge_answer(soru, iyi)
    p_guvenli, _ = judge_answer(soru, guvenli)
    assert p_kotu is not None and p_kotu <= 2
    assert p_iyi is not None and p_iyi >= 3
    assert p_guvenli is not None and p_guvenli >= 4
