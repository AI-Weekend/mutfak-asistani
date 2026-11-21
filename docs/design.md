# Tasarım — mutfak-asistani (LangGraph)

AI Weekend 201 Langflow **mutfak** track'inin (flow 01–06) LangGraph portu. Bu belge grafiği, state'i,
node ↔ Langflow blok eşlemesini, araçları, Store'u, ingestion'ı, gözlemlenebilirliği ve korumaları anlatır.

## 1. Grafik

```
                        ┌────────────── uzun girdi ──────────────┐
                        ▼                                         │
START ──► guard ──(ok)──► router ──┬─ tarif          ──► END     │
            │                      ├─ alisveris      ──► END     │
            └─ (>1000 karakter) ───┤  (agent)                    │
               kibar ret ──► END ◄─┤                             │
                                   ├─ beslenme       ──► END ◄───┘
                                   ├─ haftalik_menu  ──► END
                                   └─ konu_disi      ──► END   (kibar ret)
```

Mermaid çıktısı: `uv run python -c "from mutfak_asistani.graph import graph; print(graph.get_graph().draw_mermaid())"`.

## 2. State

```python
class State(MessagesState):   # messages: add_messages reducer ile birikir
    route: str                # guard "reddedildi", router "tarif|alisveris|beslenme|haftalik_menu|konu_disi"
```

* **Sohbet hafızası** = thread'in `messages` listesi (checkpointer saklar; `langgraph dev`/Deployment sağlar).
  Langflow'daki *Message History* bileşeninin karşılığıdır: tarif dalında son 8 mesaj `{gecmis}` olarak prompta girer;
  ajanlar son 9 mesajı görür.
* **Kalıcı veri** (alışveriş listesi) mesajlarda değil **Store**'dadır (bölüm 5).

## 3. Node'lar ↔ Langflow blokları

| LangGraph | Langflow (04-araclar / 06-izleme) | Not |
|---|---|---|
| `guard` | — | Yeni: ucuz koruma (girdi uzunluğu) |
| `router` | **Smart Router** + xAI modeli | `with_structured_output(RouteDecision)`; rota açıklamaları Langflow'dan aynen |
| `tarif` | **Prompt Template** (CoT + `{gecmis}` + `{tarifler}` + kurallar) → xAI → Chat Output | Prompt aynen; `{alerjen_kontrolu}` bloğu eklendi |
| tarif içi retriever | **File → Split Text → Knowledge (yaz/oku) → Parser** | Bellek içi numpy deposu (bölüm 6) |
| tarif içi hafıza | **Message History** | `_history()` |
| `alisveris` | **Agent "Alışveriş listesi"** + Tavily + Calculator + MCP notlar klasörü | `create_agent`; MCP dosyası → Store |
| `beslenme` | **Agent "Beslenme"** | System prompt aynen; calculator + web arama |
| `haftalik_menu` | — (uzantı) | `create_agent`: `tarif_ara`, `alerjen_kontrol`, `menu_kurallarini_dogrula`, `calculator` |
| `konu_disi` | — (uzantı) | Router'ın 5. rotası; kibar ret |
| `alerjen_kontrol` | — (uzantı) | Deterministik kod (`household.py`) + araç + tarif dalına enjekte blok |
| `evals/judge.py` | **Hakem** (06-izleme) | Rubrik aynen (1–5) |
| `evals/golden.py` + `create_dataset.py` | Trace → golden dataset dersi | LangSmith dataset `mutfak-asistani-golden` |
| LangSmith tracing | Langflow **Traces** sekmesi | `LANGSMITH_TRACING=true` |

Flow ↔ özellik: 01 temel (tek model) → `tarif` node'u; 02 akış (router) → `router`; 03 hafıza → `messages`/`{gecmis}`;
04 araçlar → `alisveris`/`beslenme` ajanları; 05 yayın → `langgraph.json` + Deployment; 06 izleme → LangSmith + `evals/`.

## 4. Araçlar (`tools.py`)

| Araç | Kim kullanır | Davranış |
|---|---|---|
| `calculator` | alisveris, beslenme, haftalik_menu | AST tabanlı güvenli aritmetik (`eval` yok) |
| `web_search` | alisveris, beslenme | Tavily `max_results=3` (üst sınır sabit ≤3), `search_depth="basic"`. `TAVILY_API_KEY` yoksa ya da hata olursa "arama kapalı" metni döner, ajan çökmez |
| `read_list` / `append_list` / `edit_list` | alisveris | Store'a okur/yazar (bölüm 5) |
| `tarif_ara` | haftalik_menu | Tarif defteri araması |
| `alerjen_kontrol` | haftalik_menu | Tarifin "Alerjen bilgisi"ni hane notlarıyla karşılaştırır |
| `menu_kurallarini_dogrula` | haftalik_menu | ≤1 börek/hamur işi, fıstık yok |

### Alerjen kontrolü
`household.check_recipe` yalnızca **olumlu** eşleşmeleri sayar (malzeme listesi + "İçerir:" cümlesi): "Yer fıstığı / sert kabuklu
yemiş: yok" ifadesi fıstık sayılmaz. Susam ve hardal bilerek uyarı üretmez (evde herkes yiyebiliyor). Güvenlik kritik
kural LLM'e bırakılmadı: tarif dalında retriever'ın getirdiği her tarif için rapor üretilip prompta eklenir.

## 5. Store (alışveriş listesi)

Langflow'da ajan MCP **filesystem** sunucusuyla `alisveris.md` dosyasını okuyup yazıyordu. LangGraph'ta aynı iş **Store** ile:

| MCP (Langflow) | LangGraph |
|---|---|
| izinli klasör `notlar/` | namespace `("alisveris", <thread_id>)` (auth varsa `<anon:/user: kimliği>`) |
| dosya `alisveris.md` | key `"liste"`, değer `{"text": "<markdown>"}` |
| `list_allowed_directories` | (gerekmez; namespace araç içinde belirlenir) |
| `read_file` | `read_list` |
| `append_file` | `append_list` (başlık yoksa `## Alınacaklar` oluşturur) |
| `edit_file` | `edit_list` |

**Liste kimin? (güvenlik)** `_namespace` sırası:

1. `langgraph_auth_user_id` — yalnızca `anon:` / `user:` önekliyse (custom auth handler'ın ürettiği kimlik);
2. `configurable.user_id` — yalnızca `MUTFAK_TRUST_USER_ID=1` iken (yerel test; **istemci kontrollüdür**, üretimde kapalı);
3. `thread_id` (varsayılan); 4. `"varsayilan"`.

Gerekçe: genel demoda tüm ziyaretçiler tek bir Agent Chat UI proxy'si ve tek LangSmith API anahtarıyla Deployment'a ulaşır;
bu durumda `langgraph_auth_user_id` herkes için aynı (ya da boş) olur ve ona güvenmek tüm ziyaretçileri **tek ortak listede**
buluşturur; `user_id`'ye güvenmek ise başkasının kimliğini yazarak listesini okumaya izin verirdi. Bu yüzden genel demoda liste
**konuşma (thread) başınadır**. Kullanıcı başına kalıcılık için `langgraph.json`'a `"auth": {"path": "./auth.py:auth"}` ekleyip
handler'da kimliği `user:<id>` biçiminde döndürmek gerekir (bu repoda yok). Testler: `tests/test_unit.py::test_namespace_*`.

**Eşzamanlılık:** model "süt ve yumurta ekle" gibi isteklerde `append_list`'i paralel çağırabilir; Store'da
compare-and-set yok. `langgraph dev` sunucusunda tek bir kayıp güncelleme gözlendi (domates yazıldı, salatalık kayboldu);
oku-değiştir-yaz bölümüne süreç içi `threading.Lock` eklenince 3/3 deneme temiz geçti. Birim test yarışı kilitsiz
yeniden üretemedi (regresyon koruması olarak duruyor). **Sınır:** kilit süreç içidir; çok işçili dağıtımda aynı kullanıcının
eşzamanlı *ayrı run'ları* için Store öğesine sürüm alanı (optimistic concurrency) eklenmeli.

## 6. Ingestion ve retriever

* `data/*.pdf` (4 tarif) başlangıçta `pypdf` ile okunur; **tarif başına bir `Document`** (PDF'ler tek sayfa).
  Metadata: `recipe` (ilk satır), `alerjen` ("Alerjen bilgisi" bölümü), `source`.
* `RecipeStore`: bellek içi **numpy** kosinüs benzerliği; dış veritabanı yok → LangSmith Deployment'ta ek servis gerekmez.
  İndeks ilk kullanımda (`lru_cache`) kurulur; 4 tarif için maliyet ihmal edilebilir. `data/` klasörü `pyproject` ile
  pakete (`_data`) ve `langgraph.json` `dependencies: ["."]` ile imaja girer.
* Embedding **değiştirilebilir**: `OPENAI_API_KEY` varsa `text-embedding-3-small`; yoksa deterministik **anahtar-kelime
  yedeği** (`KeywordEmbeddings`). Yedek anlam benzerliği vermez, yalnızca ad/malzeme eşleşmesi; test ve anahtarsız
  çalışma içindir (üretimde OpenAI kullanın). Hangisinin aktif olduğu `get_store().embeddings_name` ile görülür.
* PDF eklemek için `data/` klasörüne koyup yeniden başlatmak yeterli (ilk satır tarif adı, "Alerjen bilgisi" başlığı beklenir).

## 7. Gözlemlenebilirlik

* LangSmith: `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=mutfak-asistani`, `LANGSMITH_API_KEY`.
* Her node `add_node(..., metadata={course, node, route})` ile işaretli; model ve ajan çağrıları
  `tags=["course:ai-weekend-201", "node:<ad>"]` taşır → LangSmith'te node/rotaya göre filtrelenir.
* **Offline eval** (deploy öncesi): `evals/golden.py` (10 soru; alerji tuzakları: fıstıklı sütlaç, börek limiti, konu dışı) →
  `python -m evals.create_dataset` (LangSmith dataset) → `python -m evals.run_eval` (`langsmith.evaluate`; evaluator'lar:
  `ev_kurali_hakem` 1–5 → 0–1 ve `rota_dogru`). `--local` bayrağı LangSmith'siz çalışır ve puanları yazdırır.
* **Online eval** (deploy sonrası): gerçek trafikteki trace'leri örnekle ve aynı hakem promptunu (`prompts.JUDGE_PROMPT`)
  LangSmith *online evaluator* olarak bağla; düşük puanlı trace'ler yeni golden örneği olur (döngü: golden → judge → deploy → trafik → hata → golden).
* Hakem rubriği Langflow 06-izleme ile aynıdır: 5 = kurallara uyuyor, 3 = kural dışı ama açıkça uyarıyor, 1 = uyarısız fıstık.

## 8. Korumalar (guards)

| Koruma | Durum | Yer |
|---|---|---|
| Girdi uzunluğu ≤ 1000 karakter, kibar ret (modele gitmez) | **Uygulandı** | `guard` node'u |
| Konu dışı mesaj reddi | **Uygulandı** | router `konu_disi` rotası |
| `max_tokens` (router 200, cevaplar 1200, hakem 300) | **Uygulandı** | `config.get_chat_model` |
| Ajan döngü sınırı (`recursion_limit=12`, aşılırsa kibar mesaj) | **Uygulandı** | `_agent_node` |
| Tavily `max_results ≤ 3`, `basic` | **Uygulandı** | `web_search` |
| Model timeout 60 sn, 2 yeniden deneme | **Uygulandı** | `get_chat_model` |
| Hesap makinesinde `eval` yok, üs sınırı | **Uygulandı** | `calculator` |
| Rate limit (IP başına istek/run) | **Uygulandı (en iyi çaba)** | `chat-ui/route.ts`: saatte 30 run, dakikada 120 istek, bellek içi. Ek olarak Vercel Firewall kuralı önerilir |
| Herkese açık proxy: uç nokta izin listesi, asistan kilidi, `config` atma, ziyaretçi başına thread (`metadata.owner` + çerez) | **Uygulandı** | `chat-ui/guard.ts` (+ `guard.test.ts`) |
| Kimlik doğrulama / yetkilendirme | **Dokümante** | Varsayılan: kimlik yok, liste thread başına (bölüm 5). Kullanıcı başına liste için LangSmith custom auth (`auth.py`, `user:<id>` kimliği) ya da gateway |
| Prompt-injection sertleştirme (kullanıcı metni "kurallar"ı geçersiz kılma) | **Kısmen** | Alerjen kuralı deterministik koddan prompta girer; ayrıca router "talimat değiştirme"yi `konu_disi` sayar. Tam koruma için çıktı doğrulayıcı (post-check) eklenebilir |
| Maliyet bütçesi / günlük token tavanı | **Dokümante** | Sağlayıcı konsolunda hard limit + LangSmith maliyet alarmı |
| PII | **Dokümante** | Trace'lerde kullanıcı metni saklanır; üretimde LangSmith anonymizer / maskeleme |

## 9. Bilinen sınırlar / bulgular

* Router belirsiz mesajlarda diyet bilgisini `beslenme`'ye yönlendirebilir (Langflow `Beslenme` tarifi "diyetini anlatıyor" içerir):
  "Babam gluteni azaltıyor ama … börek … yapsam mı?" golden sorusu `beslenme`'ye gitti (rota doğruluğu 9/10); cevap yine de kural uyumluydu.
  Rota tanımlarını daraltmak (diyet *bilgisi verme* ≠ *tarif sorma*) bir sonraki iyileştirme.
* Anahtar-kelime retriever Türkçe ek/anlam eşleşmesinde sınırlıdır; gerçek embedding ile (OpenAI) ayrıca ölçülmedi (anahtar yoktu).
* Haftalık menü maliyet tahmini modelin tahminidir (tarif defterinde fiyat yok); toplam `calculator` ile alınır.
