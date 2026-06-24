// Remote fail-open smoke: drives the real SDK against a DEPLOYED Varsten
// (staging/prod) over the real network. Driven by scripts/smoke_failopen.py
// --remote <base-url>.
//
// The credential-free checks run anywhere: a non-resolving Varsten host proves the
// SDK falls back directly to the provider under a real DNS failure (the fallback
// leg runs locally against a mock provider this harness starts). The contract
// checks that need a real project key + a Phase-2 backend are gated on
// VARSTEN_SMOKE_KEY and skipped (clearly) when it is absent.
//
// Env: VARSTEN_BASE_URL (deployed /v1), DEAD_URL (non-resolving /v1),
//      OPENAI_BASE_URL (local mock for the fallback leg), VARSTEN_SMOKE_KEY (vk_, optional).
import { VarstenOpenAI } from "../dist/index.js";

const REMOTE = process.env.VARSTEN_BASE_URL;
const DEAD = process.env.DEAD_URL;
const KEY = process.env.VARSTEN_SMOKE_KEY || "";

let failures = 0;
let skipped = 0;
function check(name, cond, detail = "") {
  if (cond) {
    console.log(`PASS ${name}`);
  } else {
    console.log(`FAIL ${name} :: ${detail}`);
    failures += 1;
  }
}
function skip(name, why) {
  console.log(`SKIP ${name} :: ${why}`);
  skipped += 1;
}
const body = (content) => ({ model: "gpt-4o-mini", messages: [{ role: "user", content }] });
const meta = (res) => res?._varsten ?? null;
async function scenario(name, fn) {
  try {
    await fn();
  } catch (err) {
    check(name, false, `threw ${err?.message ?? err}`);
  }
}

// 1. Remote health: no auth, no DB. (404 here means Phase 2 is not deployed yet.)
await scenario("remote_health", async () => {
  const r = await fetch(`${REMOTE}/health`);
  const j = await r.json().catch(() => ({}));
  check("remote_health_ok", r.status === 200 && j.ok === true, `status=${r.status} (404 => Phase 2 not deployed)`);
});

// 2. Varsten unreachable -> direct provider fallback, over a real DNS failure.
await scenario("remote_backend_down", async () => {
  const client = new VarstenOpenAI({
    varstenApiKey: KEY || "vk_smoke_placeholder",
    openaiApiKey: "sk-mock",
    baseURL: DEAD,
  });
  const res = await client.chat.completions.create(body("remote-down"));
  check("remote_unreachable_falls_back", meta(res)?.servedBy === "provider-fallback", JSON.stringify(meta(res)));
  check("remote_unreachable_reason_connection", meta(res)?.reason === "connection_error", JSON.stringify(meta(res)));
  check("remote_unreachable_has_content", Boolean(res.choices?.[0]?.message?.content), "no content on fallback");
});

// --- Contract checks: need a Phase-2 backend + a real project key. ---
if (!KEY) {
  skip("remote_optimized", "set VARSTEN_SMOKE_KEY (a staging vk_) to run");
  skip("remote_provider_error_no_fallback", "needs VARSTEN_SMOKE_KEY");
  skip("remote_telemetry_rejects_content", "needs VARSTEN_SMOKE_KEY");
} else {
  // 3. Optimized through the deployed Varsten.
  await scenario("remote_optimized", async () => {
    const client = new VarstenOpenAI({ varstenApiKey: KEY, openaiApiKey: "sk-mock", baseURL: REMOTE });
    const res = await client.chat.completions.create(body(`remote-optimized-${Date.now()}`));
    check("remote_optimized_served_by_varsten", meta(res)?.servedBy === "varsten", JSON.stringify(meta(res)));
    check("remote_optimized_has_content", Boolean(res.choices?.[0]?.message?.content), "no content");
  });

  // 4. Provider-originated error (invalid model) is relayed and surfaced, NOT
  //    retried. The deployed upstream returns a 4xx; the SDK must not fall back.
  await scenario("remote_provider_error", async () => {
    const client = new VarstenOpenAI({ varstenApiKey: KEY, openaiApiKey: "sk-mock", baseURL: REMOTE });
    let threw = null;
    let res = null;
    try {
      res = await client.chat.completions.create({
        model: "varsten-smoke-nonexistent-model",
        messages: [{ role: "user", content: "x" }],
      });
    } catch (e) {
      threw = e;
    }
    check(
      "remote_provider_error_no_fallback",
      Boolean(threw) && threw.status >= 400 && threw.status < 500,
      threw ? `status=${threw.status}` : `no throw, served ${JSON.stringify(meta(res))}`,
    );
  });

  // 5. Telemetry rejects content (and authenticates by the vk_ key).
  await scenario("remote_telemetry", async () => {
    const bad = await fetch(`${REMOTE}/telemetry/fallback`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${KEY}` },
      body: JSON.stringify({ events: [{ reason_code: "x", phase: "p", messages: [{ role: "user", content: "secret" }] }] }),
    });
    check("remote_telemetry_rejects_content", bad.status === 422, `status=${bad.status}`);
  });
}

console.log(`SMOKE_DONE failures=${failures} skipped=${skipped}`);
process.exit(failures === 0 ? 0 : 1);
