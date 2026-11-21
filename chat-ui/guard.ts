export const OWNER_COOKIE = "mutfak_anon";
export const MAX_BODY_BYTES = 16_000;
export const MAX_INPUT_CHARS = 1_000;

export type Kind =
  | "info"
  | "assistants"
  | "threadCreate"
  | "threadSearch"
  | "threadRead"
  | "runCreate"
  | "runRead"
  | "runCancel";

const RULES: Array<[method: string, pattern: RegExp, kind: Kind]> = [
  ["GET", /^info$/, "info"],
  ["GET", /^ok$/, "info"],
  ["POST", /^assistants\/search$/, "assistants"],
  ["GET", /^assistants\/[\w-]+(\/(graph|schemas|subgraphs))?$/, "assistants"],
  ["POST", /^threads$/, "threadCreate"],
  ["POST", /^threads\/search$/, "threadSearch"],
  ["GET", /^threads\/[\w-]+$/, "threadRead"],
  ["GET", /^threads\/[\w-]+\/state(\/[\w-]+)?$/, "threadRead"],
  ["GET", /^threads\/[\w-]+\/history$/, "threadRead"],
  ["POST", /^threads\/[\w-]+\/history$/, "threadRead"],
  ["POST", /^threads\/[\w-]+\/runs(\/stream|\/wait)?$/, "runCreate"],
  ["GET", /^threads\/[\w-]+\/runs\/[\w-]+(\/stream|\/join)?$/, "runRead"],
  ["GET", /^threads\/[\w-]+\/stream$/, "runRead"],
  ["POST", /^threads\/[\w-]+\/runs\/[\w-]+\/cancel$/, "runCancel"],
];

export function classify(method: string, path: string): Kind | null {
  const clean = path.replace(/^\/+|\/+$/g, "");
  for (const [m, re, kind] of RULES) {
    if (m === method && re.test(clean)) return kind;
  }
  return null;
}

type Json = Record<string, unknown>;

function messageChars(input: unknown): number {
  if (!input || typeof input !== "object") return 0;
  const messages = (input as Json).messages;
  if (!Array.isArray(messages)) return JSON.stringify(input).length;
  let total = 0;
  for (const m of messages) {
    const content = (m as Json)?.content;
    if (typeof content === "string") total += content.length;
    else total += JSON.stringify(content ?? "").length;
  }
  return total;
}

export type Sanitized = { ok: true; body: Json } | { ok: false; status: number; error: string };

export function sanitizeBody(kind: Kind, body: Json, owner: string, assistantId: string): Sanitized {
  if (kind === "threadCreate") {
    const metadata = { ...((body.metadata as Json) ?? {}), owner };
    return { ok: true, body: { ...body, metadata } };
  }
  if (kind === "threadSearch") {
    const metadata = { ...((body.metadata as Json) ?? {}), owner };
    const limit = Math.min(Number(body.limit) || 20, 50);
    return { ok: true, body: { ...body, metadata, limit } };
  }
  if (kind === "runCreate") {
    if (body.assistant_id !== assistantId) {
      return { ok: false, status: 403, error: "assistant not allowed" };
    }
    if (body.command !== undefined || body.webhook !== undefined || body.checkpoint !== undefined) {
      return { ok: false, status: 403, error: "run option not allowed" };
    }
    if (messageChars(body.input) > MAX_INPUT_CHARS) {
      return { ok: false, status: 413, error: `message longer than ${MAX_INPUT_CHARS} characters` };
    }
    const { config: _config, interrupt_before: _ib, interrupt_after: _ia, ...rest } = body;
    return { ok: true, body: { ...rest, metadata: { ...((body.metadata as Json) ?? {}), owner, via: "chat-ui" } } };
  }
  return { ok: true, body };
}

export class RateLimiter {
  private hits = new Map<string, number[]>();
  private readonly limit: number;
  private readonly windowMs: number;

  constructor(limit: number, windowMs: number) {
    this.limit = limit;
    this.windowMs = windowMs;
  }

  allow(key: string, now = Date.now()): boolean {
    const recent = (this.hits.get(key) ?? []).filter((t) => now - t < this.windowMs);
    if (recent.length >= this.limit) {
      this.hits.set(key, recent);
      return false;
    }
    recent.push(now);
    this.hits.set(key, recent);
    if (this.hits.size > 10_000) this.hits.clear();
    return true;
  }
}

export function readCookie(header: string | null, name: string): string | null {
  if (!header) return null;
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return null;
}
