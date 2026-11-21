"""Mutfak asistanı grafiği (LangGraph StateGraph).

START → guard → router ─┬─ tarif          (RAG + hafıza + CoT + alerjen kontrolü)
                         ├─ alisveris      (create_agent: Tavily + hesap makinesi + Store listesi)
                         ├─ beslenme       (create_agent: hesap makinesi [+ web arama])
                         ├─ haftalik_menu  (create_agent: tarif_ara + alerjen + menü doğrulama)
                         └─ konu_disi      (kibar ret)            → END
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from mutfak_asistani import household, prompts
from mutfak_asistani.config import (
    AGENT_RECURSION_LIMIT,
    ANSWER_MAX_TOKENS,
    COURSE,
    HISTORY_MESSAGES,
    MAX_INPUT_CHARS,
    ROUTER_MAX_TOKENS,
    get_chat_model,
    node_config,
)
from mutfak_asistani.retriever import format_recipes, get_store
from mutfak_asistani.tools import menu_tools, nutrition_tools, shopping_tools

RouteName = Literal["tarif", "alisveris", "beslenme", "haftalik_menu", "konu_disi"]


class RouteDecision(BaseModel):
    """Smart Router çıktısı."""

    route: RouteName = Field(description="Kullanıcının isteğine en uygun rota.")


class State(MessagesState):
    """Mesajlar + router'ın seçtiği rota."""

    route: str


# ----------------------------------------------------------------- yardımcılar
def _text(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return " ".join(p.get("text", "") for p in c if isinstance(p, dict))


def _last_human(messages: list[AnyMessage]) -> str:
    for m in reversed(messages):
        if m.type == "human":
            return _text(m)
    return ""


def _history(messages: list[AnyMessage]) -> str:
    """{gecmis}: son mesaj hariç, son HISTORY_MESSAGES mesaj (Langflow Message History karşılığı)."""
    prior = messages[:-1][-HISTORY_MESSAGES:]
    if not prior:
        return "(henüz geçmiş yok)"
    return "\n".join(f"{'Kullanıcı' if m.type == 'human' else 'Asistan'}: {_text(m)}" for m in prior if _text(m))


def _node_meta(config: RunnableConfig, node: str, **extra) -> RunnableConfig:
    """Üst config'e node tag/metadata ekler (LangSmith'te node ve rotaya göre filtre)."""
    nc = node_config(node, **extra)
    return {
        **config,
        "tags": [*config.get("tags", []), *nc["tags"]],
        "metadata": {**config.get("metadata", {}), **nc["metadata"]},
    }


# ----------------------------------------------------------------- node'lar
def guard(state: State) -> dict:
    """Ucuz koruma: çok uzun girdiyi modele hiç göndermeden reddet."""
    text = _last_human(state["messages"])
    if len(text) > MAX_INPUT_CHARS:
        return {
            "route": "reddedildi",
            "messages": [AIMessage(prompts.UZUN_MESAJ_CEVABI.format(limit=MAX_INPUT_CHARS))],
        }
    return {"route": ""}


def after_guard(state: State) -> Literal["router", "__end__"]:
    return "__end__" if state["route"] == "reddedildi" else "router"


def router(state: State, config: RunnableConfig) -> dict:
    """Smart Router: yapılandırılmış çıktıyla rota seç."""
    model = get_chat_model("router", ROUTER_MAX_TOKENS).with_structured_output(RouteDecision, method="json_schema")
    recent = state["messages"][-4:]
    convo = "\n".join(f"{'Kullanıcı' if m.type == 'human' else 'Asistan'}: {_text(m)[:500]}" for m in recent)
    decision = model.invoke(
        [("system", prompts.ROUTER_SYSTEM), ("human", f"Konuşma:\n{convo}\n\nHangi rota?")],
        config=_node_meta(config, "router"),
    )
    return {"route": decision.route}


def route_after_router(state: State) -> str:
    return state["route"]


def konu_disi(state: State) -> dict:
    return {"messages": [AIMessage(prompts.KONU_DISI_CEVABI)]}


def tarif(state: State, config: RunnableConfig) -> dict:
    """Tarif dalı: RAG (tarif defteri) + sohbet hafızası + CoT promptu + alerjen kontrolü."""
    cfg = _node_meta(config, "tarif", route="tarif")
    msgs = state["messages"]
    question = _last_human(msgs)
    # Takip sorularında bağlamı kaybetmemek için son iki kullanıcı mesajıyla ara.
    humans = [_text(m) for m in msgs if m.type == "human"][-2:]
    docs = get_store().search(" ".join(humans), k=3)

    reports = [household.check_recipe(d.metadata["recipe"], d.page_content).as_text() for d in docs]
    alerjen = "\n".join([household.household_notes().split("## Haftalık bütçe")[0].strip(), "", *reports])

    prompt = prompts.TARIF_PROMPT.format(
        gecmis=_history(msgs),
        tarifler=format_recipes(docs),
        alerjen_kontrolu=alerjen,
        malzemeler=question,
    )
    answer = get_chat_model("tarif", ANSWER_MAX_TOKENS).invoke(prompt, config=cfg)
    return {"messages": [AIMessage(_text(answer))]}


_GUNLER = r"(?:Pazartesi|Salı|Sali|Çarşamba|Carsamba|Perşembe|Persembe|Cuma|Cumartesi|Pazar)"


def menu_son_kontrol(answer: str) -> str:
    """Haftalık menü cevabındaki gün satırlarını koda sokup kuralları deterministik denetler.

    Model "doğruladım" deyip aracı hiç çağırmayabiliyor (smoke testte görüldü); bu yüzden
    nihai cevaba kodun ürettiği kontrol satırı eklenir. Gün satırı bulunamazsa hiçbir şey eklenmez.
    """
    import re

    yemekler = [
        m.group(1).strip()
        for line in answer.splitlines()
        if (m := re.match(rf"^\s*[-*•]\s*\**{_GUNLER}\**\s*[:：-]?\**\s*(.+)$", line, flags=re.I))
    ]
    if not yemekler:
        return ""
    sorunlar = household.check_menu(yemekler)
    if not sorunlar:
        return "\n\n🔎 Otomatik kural kontrolü (kod): fıstık yok, börek/hamur işi ≤ 1 — menü evin kurallarına uygun."
    return "\n\n⚠️ Otomatik kural kontrolü (kod) sorun buldu: " + " ".join(sorunlar) + " Menüyü bu kurala göre düzeltmemi ister misin?"


def _agent_node(name: str, tools: list, system_prompt: str, post=None):
    """create_agent'ı kısa recursion_limit ile sarar; yalnızca yeni mesajları döndürür.

    Ajan ilk çağrıda kurulur (model anahtarı import anında gerekmesin diye).
    """

    @lru_cache(maxsize=1)
    def agent():
        return create_agent(
            get_chat_model(name, ANSWER_MAX_TOKENS),
            tools=tools,
            system_prompt=system_prompt,
            name=name,
        )

    def node(state: State, config: RunnableConfig) -> dict:
        inp = state["messages"][-(HISTORY_MESSAGES + 1) :]
        cfg = {**_node_meta(config, name, route=name), "recursion_limit": AGENT_RECURSION_LIMIT}
        try:
            out = agent().invoke({"messages": inp}, cfg)
        except GraphRecursionError:
            return {
                "messages": [
                    AIMessage("İşlem çok uzadı, durdurdum. İsteği biraz daha basit hâliyle tekrar yazar mısın?")
                ]
            }
        new = out["messages"][len(inp) :]
        if post and new and new[-1].type == "ai":
            extra = post(_text(new[-1]))
            if extra:
                new[-1] = AIMessage(_text(new[-1]) + extra, id=new[-1].id)
        return {"messages": new}

    node.__name__ = name
    return node


def build_graph(*, checkpointer=None, store=None):
    """Grafiği derler. langgraph dev/Deployment checkpointer ve store'u kendisi verir."""
    builder = StateGraph(State)
    meta = {"course": COURSE}
    builder.add_node("guard", guard, metadata={**meta, "node": "guard"})
    builder.add_node("router", router, metadata={**meta, "node": "router"})
    builder.add_node("tarif", tarif, metadata={**meta, "node": "tarif", "route": "tarif"})
    builder.add_node(
        "alisveris",
        _agent_node("alisveris", shopping_tools(), prompts.ALISVERIS_SYSTEM),
        metadata={**meta, "node": "alisveris", "route": "alisveris"},
    )
    builder.add_node(
        "beslenme",
        _agent_node("beslenme", nutrition_tools(), prompts.BESLENME_SYSTEM),
        metadata={**meta, "node": "beslenme", "route": "beslenme"},
    )
    builder.add_node(
        "haftalik_menu",
        _agent_node("haftalik_menu", menu_tools(), prompts.HAFTALIK_MENU_SYSTEM.replace("{notlar}", household.household_notes()), post=menu_son_kontrol),
        metadata={**meta, "node": "haftalik_menu", "route": "haftalik_menu"},
    )
    builder.add_node("konu_disi", konu_disi, metadata={**meta, "node": "konu_disi", "route": "konu_disi"})

    builder.add_edge(START, "guard")
    builder.add_conditional_edges("guard", after_guard, {"router": "router", "__end__": END})
    builder.add_conditional_edges(
        "router",
        route_after_router,
        {r: r for r in ("tarif", "alisveris", "beslenme", "haftalik_menu", "konu_disi")},
    )
    for n in ("tarif", "alisveris", "beslenme", "haftalik_menu", "konu_disi"):
        builder.add_edge(n, END)
    return builder.compile(checkpointer=checkpointer, store=store, name="mutfak_asistani")


# langgraph.json bu nesneyi gösterir.
graph = build_graph()
