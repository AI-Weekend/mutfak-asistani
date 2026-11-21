# chat-ui — Agent Chat UI için korumalı proxy

Herkese açık sohbet sayfası: [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui)
(Next.js) + bu klasördeki **korumalı API proxy'si**. LangSmith API anahtarı yalnızca sunucuda
(Vercel ortam değişkeni) durur; tarayıcı anahtarı hiç görmez.

## Neden yalnızca hazır passthrough değil?

Agent Chat UI'nin hazır `langgraph-nextjs-api-passthrough` route'u **her isteği** anahtarla
deployment'a iletir: linki bilen herkes thread'leri listeleyebilir/silebilir, Store'u okuyabilir,
istediği kadar run başlatabilir. `route.ts` + `guard.ts` bunu daraltır:

| Koruma | Ne yapar |
| --- | --- |
| Uç nokta izin listesi | Yalnızca UI'nin kullandığı uçlar: `info`, `assistants` okuma, `threads` oluştur/ara/oku, `threads/{id}/runs` başlat/izle/iptal. `store/*`, `crons`, `DELETE`, `PATCH`, asistan oluşturma/düzenleme, durumsuz `runs/stream` → 403/405 |
| Ziyaretçi ayrımı | Tarayıcıya httpOnly `mutfak_anon` çerezi; thread'lerin `metadata.owner` alanı buna göre yazılır, `threads/search` buna göre süzülür → kimse başkasının sohbet geçmişini görmez |
| Run kısıtları | Yalnızca `mutfak_asistani` asistanı; istemcinin gönderdiği `config` (ör. `recursion_limit`) atılır; `webhook`/`command`/`checkpoint` reddedilir; mesaj ≤ 1000 karakter; gövde ≤ 16 KB |
| Hız sınırı | IP başına saatte 30 run, dakikada 120 istek (`RUNS_PER_IP_PER_HOUR`, `REQUESTS_PER_IP_PER_MINUTE`). Bellek içidir, sunucu örneği başınadır → yalnızca ilk savunma hattı |

Grafiğin kendi korumaları (girdi sınırı, konu dışı ret, `max_tokens`, ajan `recursion_limit`,
Tavily ≤ 3 sonuç) bunlara ek olarak çalışır.

## Kurulum (Vercel)

1. `langchain-ai/agent-chat-ui` reposunu kendi GitHub hesabına/organizasyonuna fork'la.
2. Fork'ta `src/app/api/[..._path]/route.ts` dosyasını bu klasördeki `route.ts` ile değiştir,
   yanına `guard.ts`'yi kopyala.
3. Vercel'de fork'u içe aktar (Framework: Next.js) ve ortam değişkenlerini gir:

   | Değişken | Değer |
   | --- | --- |
   | `NEXT_PUBLIC_ASSISTANT_ID` | `mutfak_asistani` |
   | `NEXT_PUBLIC_API_URL` | `https://<vercel-alan-adın>/api` |
   | `LANGGRAPH_API_URL` | LangSmith → Agent Servers → sunucun → **URL** |
   | `LANGSMITH_API_KEY` | LangSmith API anahtarı (`lsv2_...`). **`NEXT_PUBLIC_` öneki koyma** |

4. Deploy et, sayfayı aç, "Elif geliyor, fıstıklı sütlaç yapsam olur mu?" diye sor.

## Ek önerilen korumalar (elle)

- Vercel Firewall'da `/api/threads/*/runs/*` için IP başına rate-limit kuralı (plan kapsamını Vercel'de kontrol et).
- xAI, OpenAI ve Tavily konsollarında **aylık harcama limiti**.
- Etkinlik bitince Vercel projesini durdur veya `LANGSMITH_API_KEY`'i sil / anahtarı LangSmith'te iptal et.
- Daha sıkı erişim gerekirse: deployment'a custom auth (`langgraph.json` → `"auth": {"path": "./auth.py:auth"}`)
  ve proxy'yi kaldırmak — bkz. `docs/design.md`.

## Test

```bash
node --test chat-ui/guard.test.ts   # Node 22.18+ / 24 (TypeScript tip silme)
```
