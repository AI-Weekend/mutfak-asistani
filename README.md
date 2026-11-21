# mutfak-asistani

AI Weekend **201** Langflow *mutfak* track'inin (flow 01–06) **LangGraph** portu: tarif defterinden RAG, sohbet hafızası,
alışveriş listesi (Store), beslenme, haftalık menü, alerjen kontrolü ve LangSmith ile izleme/eval.

* Model: xAI **grok-4.3** (`langchain-xai`, `ChatXAI`) — router ve ajanlar
* Embedding: OpenAI `text-embedding-3-small` (anahtar yoksa anahtar-kelime yedeği)
* Web arama: Tavily (`max_results=3`, `basic`; anahtar yoksa araç "kapalı" der)
* Tasarım ayrıntıları: [`docs/design.md`](docs/design.md)

## Hızlı başlangıç

```bash
uv sync                      # Python ≥3.12, bağımlılıklar kilitli (uv.lock)
cp .env.example .env         # anahtarları doldur (.env git'e girmez)
uv run langgraph dev         # http://127.0.0.1:2024 — Studio / API
```

Gerekli anahtarlar `.env.example`'da: `XAI_API_KEY` (zorunlu), `OPENAI_API_KEY`, `TAVILY_API_KEY`,
`LANGSMITH_API_KEY` (+ `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=mutfak-asistani`).

**Kurumsal TLS denetimi olan Mac:** `MUTFAK_TRUSTSTORE=1` ile sistem sertifika deposu kullanılır
(`truststore.inject_into_ssl()`; yalnızca bu değişken açıkken çalışır, bulutu etkilemez).

Kod içinden:

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from mutfak_asistani.graph import build_graph

app = build_graph(checkpointer=InMemorySaver(), store=InMemoryStore())
cfg = {"configurable": {"thread_id": "t1"}}
print(app.invoke({"messages": [("user", "Elimde mercimek ve havuç var, ne pişireyim?")]}, cfg)["messages"][-1].content)
```

## Ne yapar?

```
START → guard → router ─┬─ tarif          RAG + hafıza + CoT + alerjen kontrolü
                         ├─ alisveris      ajan: web arama + hesap makinesi + alışveriş listesi (Store)
                         ├─ beslenme       ajan: besin değerleri
                         ├─ haftalik_menu  ajan: kurallara uyan 7 günlük menü
                         └─ konu_disi      kibar ret
```

Örnek sorular: *"Elimde kırmızı mercimek ve havuç var"* (tarif) · *"Listeme süt ve yumurta ekle"* (alışveriş) ·
*"Bir porsiyon mercimek çorbasının kalorisi?"* (beslenme) · *"1.500 TL'ye haftalık menü"* (menü).

Evin kuralları `data/notlar/alisveris.md`'den gelir: kuzen Elif'in yer fıstığı + Antep fıstığı alerjisi, babanın
haftada en fazla bir börek/hamur işi sınırı, 1.500 TL haftalık bütçe. Susam ve hardal serbest.

## Langflow flow'larıyla eşleme (01–06)

| Flow | Langflow'da | Burada |
|---|---|---|
| 01 temel | Chat Input → Prompt → xAI → Chat Output | `tarif` node'u (`prompts.TARIF_PROMPT`) |
| 02 akış | Smart Router + uzmanlar | `router` (structured output) + koşullu kenarlar |
| 03 hafıza | Message History + Knowledge (RAG) | thread `messages` → `{gecmis}`; `retriever.py` + `ingestion.py` |
| 04 araçlar | Agent + Tavily + Calculator + **MCP filesystem** | `create_agent` + `tools.py`; **MCP dosyası → Store** |
| 05 yayın | Langflow API / embed | `langgraph.json` → LangSmith Deployment (bkz. Deploy) |
| 06 izleme | Traces + Hakem (LLM judge) | LangSmith tracing + `evals/` |

### MCP dosyası → LangGraph Store

| MCP filesystem | Store |
|---|---|
| `notlar/alisveris.md` dosyası | namespace `("alisveris", <thread_id>)`, key `"liste"` |
| `read_file` | `read_list` |
| `append_file` | `append_list` |
| `edit_file` | `edit_list` |
| `list_allowed_directories` | gerekmez (namespace araç içinde) |

**Liste kimin?** Varsayılan olarak **konuşma (thread) başınadır**: genel demo'da herkes tek bir proxy ve tek LangSmith
anahtarıyla bağlandığından `langgraph_auth_user_id` herkes için aynı/boş olur, `config.configurable.user_id` ise
istemci kontrollüdür — ikisine de güvenilmez (başkasının listesine erişilebilirdi). Sıra:

1. `langgraph_auth_user_id` — **yalnızca** custom auth handler'ın verdiği `anon:` / `user:` önekli kimlikler
2. `user_id` — yalnızca `MUTFAK_TRUST_USER_ID=1` iken (yerel test)
3. `thread_id` (varsayılan) → 4. `"varsayilan"`

Kullanıcı başına kalıcı liste (thread'ler arası) için custom auth gerekir:
`langgraph.json` içine `"auth": {"path": "./auth.py:auth"}` ekleyip `auth.py`'de kimliği `user:<id>` olarak döndürün
(bu repoda auth handler yok; bkz. `docs/design.md` §5, §8).

## Testler

```bash
uv run pytest tests/test_unit.py            # ağ yok: hane kuralları, retriever, araçlar, Store namespace, guard
uv run pytest tests/test_live.py            # gerçek grok çağrıları (XAI_API_KEY gerekir)
uv run python scripts/local.py scripts.smoke   # canlı smoke; çıktı Markdown
```

`test_live.py` yönlendirmeyi (5 rota), RAG'ın tarif adını anmasını, hafızayı (gluten → börek yok),
Store'da ekle→oku akışını ve hakemin fıstıklı cevabı ≤2, güvenli cevabı ≥4 puanlamasını doğrular.
Anahtar yoksa atlanır. `scripts/local.py` yalnızca yerel geliştirme içindir (TLS + `XAI_API_KEY`'i ortamdan ya da `MUTFAK_LOCAL_ENV_FILE=<.env yolu>` ile gösterilen dosyadan yükler).

> Test notu: bu repo geliştirilirken OpenAI/Tavily/LangSmith anahtarı yoktu. Testler **gerçek grok**, fakat **anahtar-kelime
> retriever** ve **kapalı Tavily** ile koştu; OpenAI embedding, Tavily ve LangSmith yolları gerçek servisle denenmedi.

## Eval (LangSmith)

```bash
uv run python -m evals.create_dataset        # LangSmith'te "mutfak-asistani-golden" (10 Türkçe soru)
uv run python -m evals.run_eval              # langsmith.evaluate: ev_kurali_hakem (1–5) + rota_dogru
uv run python -m evals.run_eval --local      # LangSmith'siz: puanları yazdırır
```

Hakem rubriği Langflow 06-izleme ile aynıdır (5 = kurallara uyuyor · 3 = kural dışı ama uyarıyor · 1 = uyarısız fıstık).
Offline (golden, merge öncesi) ve online (deploy sonrası trace örnekleme) döngüsü için `docs/design.md` §7.

## Korumalar

Girdi uzunluk sınırı (1000 karakter), konu dışı ret, `max_tokens`, ajan `recursion_limit`, Tavily ≤3 sonuç uygulandı.
Herkese açık sayfa için uç nokta izin listesi, ziyaretçi başına thread ayrımı ve IP hız sınırı `chat-ui/` proxy'sinde — bkz. `chat-ui/README.md` ve `docs/design.md` §8.

## Deploy

İki parça: **LangSmith Deployment** (Agent Server, grafiği çalıştırır) + **Agent Chat UI** (Vercel'de herkese açık sohbet sayfası,
korumalı proxy ile — bkz. [`chat-ui/README.md`](chat-ui/README.md)). Fiyatlar 21 Kasım 2026'da langchain.com/pricing'den okundu.

1. **LangSmith hesabı** aç (smith.langchain.com). Deployment için **Plus** planı gerekir: koltuk başı **39 $/ay**,
   **1 küçük serverless Agent Server ücretsiz** dahil; ek sunucular kaynak kullanımına göre ücretlenir. Developer (ücretsiz) planda deployment yok.
2. **API anahtarı** oluştur (Settings → API Keys) → bu anahtar yalnızca Vercel'e ve yerel `.env`'e girer.
3. **GitHub bağlantısı:** Agent Servers → **+ Agent Server** → Source: **GitHub repository** → `hosted-langserve` GitHub uygulamasını
   `AI-Weekend` organizasyonunda yetkilendir (org sahibi/admin gerekir; "Only select repositories" → `mutfak-asistani`).
4. **Sunucuyu oluştur:**
   | Alan | Değer |
   | --- | --- |
   | Repository | `AI-Weekend/mutfak-asistani` |
   | Name | `mutfak-asistani` |
   | Git Ref (Branch or Tag) | `main` |
   | LangGraph API config file | `langgraph.json` |
   | Automatically update Agent Server on push to branch | açık |
   | Agent Server type | **Serverless** (ücretsiz küçük sunucu; soğuk başlangıç olabilir) |
   | Shareable through Studio | kapalı |
   | Environment variables / secrets | `XAI_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_PROJECT=mutfak-asistani`, `LANGSMITH_TRACING=true` |
5. **Submit** → Agent Server detayındaki **URL**'yi kopyala (örn. `https://mutfak-asistani-….us.langgraph.app`).
   Deployment isteklerini `X-Api-Key: <LangSmith anahtarı>` ile doğrular; anahtarı tarayıcıya koyma.
6. **Sohbet sayfası:** `chat-ui/README.md`'deki adımlar (agent-chat-ui fork + korumalı `route.ts` + Vercel ortam değişkenleri).
7. **Harcama limitleri:** xAI, OpenAI ve Tavily konsollarında aylık limit; etkinlik sonrası anahtarı iptal et.

Alternatif (CLI, beta): `uv tool install langgraph-cli` → `.env`'e `LANGSMITH_API_KEY` → `langgraph deploy --name mutfak-asistani`.
