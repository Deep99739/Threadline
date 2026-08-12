import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the complete Threadline product surface", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Threadline: Evidence-bound engineering handoffs<\/title>/i);
  assert.match(html, /<meta property="og:image" content="http:\/\/localhost(?::3000)?\/og.png"/i);
  assert.match(html, /<meta name="twitter:card" content="summary_large_image"/i);
  assert.match(html, /Resume engineering work from evidence, not summaries/);
  assert.match(html, /Inspect the handoff/);
  assert.match(html, /Evidence-ranked context/);
  assert.match(html, /run_job calls RetryPolicy/);
  assert.match(html, /CONTRADICTED/);
  assert.match(html, /A second agent continued the task from the handoff/);
  assert.match(html, /Eleven deterministic synthetic regression cases/);
  assert.match(html, /Keep your coding agent/);
  assert.match(html, /threadline connect codex/);
  assert.match(html, /The evidence contract/);
  assert.doesNotMatch(html, /Why I built it/);
  assert.doesNotMatch(html, /—|linear-gradient|radial-gradient/i);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("marks the synthetic fallback honestly", async () => {
  const response = await render();
  const html = await response.text();

  assert.match(html, /synthetic retry task with deliberately conflicting evidence/);
  assert.match(html, /not an external accuracy, adoption, or production claim/);
  assert.match(html, /Checking local evidence/);
  assert.doesNotMatch(html, /99%|thousands of users|production-ready/i);
});
