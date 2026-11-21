import assert from "node:assert/strict";
import { test } from "node:test";
import { classify, RateLimiter, readCookie, sanitizeBody } from "./guard.ts";

const ASSISTANT = "mutfak_asistani";
const OWNER = "anon:0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0";

test("allows the endpoints Agent Chat UI needs", () => {
  assert.equal(classify("GET", "info"), "info");
  assert.equal(classify("POST", "threads"), "threadCreate");
  assert.equal(classify("POST", "threads/search"), "threadSearch");
  assert.equal(classify("POST", "threads/abc-123/history"), "threadRead");
  assert.equal(classify("GET", "threads/abc-123/state"), "threadRead");
  assert.equal(classify("POST", "threads/abc-123/runs/stream"), "runCreate");
  assert.equal(classify("GET", "threads/abc-123/runs/r-1/stream"), "runRead");
  assert.equal(classify("POST", "threads/abc-123/runs/r-1/cancel"), "runCancel");
});

test("blocks store, crons, deletes, assistant edits and stateless runs", () => {
  assert.equal(classify("POST", "store/items/search"), null);
  assert.equal(classify("PUT", "store/items"), null);
  assert.equal(classify("POST", "runs/crons"), null);
  assert.equal(classify("DELETE", "threads/abc"), null);
  assert.equal(classify("POST", "assistants"), null);
  assert.equal(classify("PATCH", "assistants/abc"), null);
  assert.equal(classify("PATCH", "threads/abc"), null);
  assert.equal(classify("POST", "runs/stream"), null);
  assert.equal(classify("POST", "threads/abc/state"), null);
});

test("thread create and search are scoped to the visitor", () => {
  const created = sanitizeBody("threadCreate", { metadata: { owner: "someone-else" } }, OWNER, ASSISTANT);
  assert.ok(created.ok);
  assert.equal((created.body.metadata as Record<string, unknown>).owner, OWNER);

  const search = sanitizeBody("threadSearch", { metadata: { graph_id: ASSISTANT }, limit: 1000 }, OWNER, ASSISTANT);
  assert.ok(search.ok);
  assert.deepEqual(search.body.metadata, { graph_id: ASSISTANT, owner: OWNER });
  assert.equal(search.body.limit, 50);
});

test("runs: only our assistant, no config overrides, short input", () => {
  const ok = sanitizeBody(
    "runCreate",
    {
      assistant_id: ASSISTANT,
      input: { messages: [{ type: "human", content: "Mercimek çorbası nasıl yapılır?" }] },
      config: { recursion_limit: 10_000, configurable: { user_id: "x" } },
      stream_mode: ["values"],
    },
    OWNER,
    ASSISTANT,
  );
  assert.ok(ok.ok);
  assert.equal(ok.body.config, undefined);
  assert.deepEqual(ok.body.stream_mode, ["values"]);

  const other = sanitizeBody("runCreate", { assistant_id: "other" }, OWNER, ASSISTANT);
  assert.equal(other.ok, false);

  const long = sanitizeBody(
    "runCreate",
    { assistant_id: ASSISTANT, input: { messages: [{ type: "human", content: "x".repeat(1001) }] } },
    OWNER,
    ASSISTANT,
  );
  assert.ok(!long.ok && long.status === 413);

  const webhook = sanitizeBody("runCreate", { assistant_id: ASSISTANT, webhook: "https://x" }, OWNER, ASSISTANT);
  assert.equal(webhook.ok, false);
});

test("rate limiter blocks after the limit and recovers after the window", () => {
  const rl = new RateLimiter(2, 1000);
  assert.ok(rl.allow("ip", 0));
  assert.ok(rl.allow("ip", 10));
  assert.ok(!rl.allow("ip", 20));
  assert.ok(rl.allow("other", 20));
  assert.ok(rl.allow("ip", 1500));
});

test("reads the owner cookie", () => {
  assert.equal(readCookie("a=1; mutfak_anon=abc; b=2", "mutfak_anon"), "abc");
  assert.equal(readCookie(null, "mutfak_anon"), null);
});
