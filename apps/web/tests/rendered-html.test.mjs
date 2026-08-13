import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";

let server;
let origin;

function availablePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      probe.close(() => resolve(address.port));
    });
  });
}

async function waitForServer(url) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Next.js server did not become ready");
}

before(async () => {
  const port = await availablePort();
  origin = `http://127.0.0.1:${port}`;
  const next = new URL("../node_modules/next/dist/bin/next", import.meta.url);
  server = spawn(process.execPath, [next.pathname, "start", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: new URL("..", import.meta.url),
    stdio: "ignore",
  });
  await waitForServer(origin);
});

after(() => {
  server?.kill("SIGTERM");
});

function render() {
  return fetch(origin, { headers: { accept: "text/html" } });
}

test("server-renders the complete Threadline product surface", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Threadline: Evidence-bound engineering handoffs<\/title>/i);
  assert.match(html, /<meta property="og:image" content="http:\/(?:\/localhost(?::3000)?|\/127\.0\.0\.1:\d+)\/og.png"/i);
  assert.match(html, /<link rel="icon" href="\/icon\.svg/);
  assert.match(html, /<meta name="twitter:card" content="summary_large_image"/i);
  assert.match(html, /Resume engineering work from evidence, not summaries/);
  assert.match(html, /Inspect the handoff/);
  assert.match(html, /Evidence-ranked context/);
  assert.match(html, /run_job calls RetryPolicy/);
  assert.match(html, /CONTRADICTED/);
  assert.match(html, /A second agent continued the task from the handoff/);
  assert.match(html, /Twelve deterministic synthetic regression cases/);
  assert.match(html, /73\.9%/);
  assert.match(html, /Keep your coding agent/);
  assert.match(html, /pipx install git\+https:\/\/github\.com\/Deep99739\/Threadline\.git/);
  assert.match(html, /threadline onboard/);
  assert.match(html, /--client codex/);
  assert.doesNotMatch(html, /threadline init|threadline connect codex/);
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
