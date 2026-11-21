import { NextRequest, NextResponse } from "next/server";
import { classify, MAX_BODY_BYTES, OWNER_COOKIE, RateLimiter, readCookie, sanitizeBody } from "./guard";

export const runtime = "nodejs";

const API_URL = process.env.LANGGRAPH_API_URL ?? "";
const API_KEY = process.env.LANGSMITH_API_KEY ?? "";
const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "mutfak_asistani";

// In-memory limits are per server instance, so they are only a first line of defence;
// pair them with a Vercel Firewall rate-limit rule and provider spend limits.
const runLimiter = new RateLimiter(Number(process.env.RUNS_PER_IP_PER_HOUR ?? 30), 60 * 60 * 1000);
const requestLimiter = new RateLimiter(Number(process.env.REQUESTS_PER_IP_PER_MINUTE ?? 120), 60 * 1000);

function deny(status: number, error: string) {
  return NextResponse.json({ error }, { status });
}

async function handle(req: NextRequest, method: string) {
  if (!API_URL || !API_KEY) return deny(500, "proxy not configured");

  const path = req.nextUrl.pathname.replace(/^\/?api\/?/, "");
  const kind = classify(method, path);
  if (!kind) return deny(403, "endpoint not allowed");

  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  if (!requestLimiter.allow(ip)) return deny(429, "too many requests");
  if (kind === "runCreate" && !runLimiter.allow(ip)) {
    return deny(429, "Saatlik mesaj sınırına ulaştın, biraz sonra tekrar dene.");
  }

  const existingOwner = readCookie(req.headers.get("cookie"), OWNER_COOKIE);
  const owner = existingOwner && /^[\w-]{16,64}$/.test(existingOwner) ? existingOwner : crypto.randomUUID();

  let body: string | undefined;
  if (method === "POST") {
    const raw = await req.text();
    if (raw.length > MAX_BODY_BYTES) return deny(413, "request too large");
    let parsed: Record<string, unknown>;
    try {
      parsed = raw ? JSON.parse(raw) : {};
    } catch {
      return deny(400, "invalid json");
    }
    const result = sanitizeBody(kind, parsed, `anon:${owner}`, ASSISTANT_ID);
    if (!result.ok) return deny(result.status, result.error);
    body = JSON.stringify(result.body);
  }

  const search = new URLSearchParams(req.nextUrl.search);
  search.delete("_path");
  search.delete("nxtP_path");
  const qs = search.toString() ? `?${search}` : "";

  const upstream = await fetch(`${API_URL.replace(/\/$/, "")}/${path}${qs}`, {
    method,
    headers: {
      "content-type": "application/json",
      accept: req.headers.get("accept") ?? "*/*",
      "x-api-key": API_KEY,
    },
    body,
    signal: req.signal,
  });

  const headers = new Headers();
  for (const name of ["content-type", "content-location", "cache-control"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  const res = new NextResponse(upstream.body, { status: upstream.status, headers });
  if (owner !== existingOwner) {
    res.cookies.set(OWNER_COOKIE, owner, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });
  }
  return res;
}

export const GET = (req: NextRequest) => handle(req, "GET");
export const POST = (req: NextRequest) => handle(req, "POST");
