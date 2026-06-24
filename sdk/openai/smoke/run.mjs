// End-to-end SDK smoke runner. Driven by scripts/smoke_failopen.py, which stands
// up the real Varsten backend and a mock provider, then runs this against them.
//
// Uses the built package (../dist). Each scenario is isolated so one failure does
// not abort the rest. Exit code is non-zero if any check fails.
//
// Env: VARSTEN_API_KEY, OPENAI_API_KEY, VARSTEN_BASE_URL, OPENAI_BASE_URL,
//      MOCK_URL (control plane for the mock), BACKEND_DOWN_URL (a dead port).
import { VarstenOpenAI } from "../dist/index.js";

const MOCK = process.env.MOCK_URL;
const BACKEND = process.env.VARSTEN_BASE_URL;
const DEAD = process.env.BACKEND_DOWN_URL;
const KEY = process.env.VARSTEN_API_KEY;

let failures = 0;
function check(name, cond, detail = "") {
  if (cond) {
    console.log(`PASS ${name}`);
  } else {
    console.log(`FAIL ${name} :: ${detail}`);
    failures += 1;
  }
}

async function setMode(mode) {
  const r = await fetch(`${MOCK}/__mode`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (r.status !== 200) throw new Error(`mock setMode failed: ${r.status}`);
}

const body = (content) => ({ model: "gpt-4o-mini", messages: [{ role: "user", content }] });
const meta = (res) => res?._varsten ?? null;

async function scenario(name, fn) {
  try {
    await fn();
  } catch (err) {
    check(name, false, `threw ${err?.name ?? ""} ${err?.message ?? err}`);
  }
}

// A. Healthy: optimized through Varsten, ledger written server-side.
await scenario("optimized", async () => {
  await setMode("ok");
  const client = new VarstenOpenAI({});
  const res = await client.chat.completions.create(body(`optimized-${Date.now()}`));
  check("optimized_served_by_varsten", meta(res)?.servedBy === "varsten", JSON.stringify(meta(res)));
  check("optimized_has_content", Boolean(res.choices?.[0]?.message?.content), JSON.stringify(res.choices?.[0]));
});

// D. Provider 400 relayed by Varsten: surfaced, NOT retried (no double call).
await scenario("provider_error", async () => {
  await setMode("fail_400");
  const client = new VarstenOpenAI({});
  let threw = null;
  let res = null;
  try {
    res = await client.chat.completions.create(body("provider-400"));
  } catch (e) {
    threw = e;
  }
  check("provider_400_surfaced", Boolean(threw) && threw.status === 400, threw ? `status=${threw.status}` : `no throw: ${JSON.stringify(meta(res))}`);
  await setMode("ok");
});

// E. Health endpoint (no auth, no DB).
await scenario("health", async () => {
  const r = await fetch(`${BACKEND}/health`);
  const j = await r.json().catch(() => ({}));
  check("health_ok", r.status === 200 && j.ok === true, `status=${r.status}`);
});

// F. Telemetry endpoint: accepts a marker, rejects content.
await scenario("telemetry", async () => {
  const ok = await fetch(`${BACKEND}/telemetry/fallback`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${KEY}` },
    body: JSON.stringify({ events: [{ reason_code: "connection_error", phase: "pre-request", model: "gpt-4o-mini", latency_ms: 5 }] }),
  });
  check("telemetry_accepts_marker", ok.status === 202, `status=${ok.status}`);
  const bad = await fetch(`${BACKEND}/telemetry/fallback`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${KEY}` },
    body: JSON.stringify({ events: [{ reason_code: "x", phase: "p", messages: [{ role: "user", content: "secret" }] }] }),
  });
  check("telemetry_rejects_content", bad.status === 422, `status=${bad.status}`);
});

// B. Backend unreachable: fall back directly to the provider.
await scenario("backend_down", async () => {
  await setMode("ok");
  const client = new VarstenOpenAI({ baseURL: DEAD });
  const res = await client.chat.completions.create(body("backend-down"));
  check("backend_down_falls_back", meta(res)?.servedBy === "provider-fallback", JSON.stringify(meta(res)));
  check("backend_down_has_content", Boolean(res.choices?.[0]?.message?.content), "no content on fallback");
});

// C. Varsten circuit opens (real backend breaker), then falls back. Run last: it
// leaves the per-project breaker open for its cooldown.
await scenario("circuit_open", async () => {
  const client = new VarstenOpenAI({});
  await setMode("fail_500");
  for (let i = 0; i < 7; i += 1) {
    try {
      await client.chat.completions.create(body(`trip-${i}`));
    } catch {
      // provider 5xx is relayed (origin=provider) and rethrown; it trips the
      // backend breaker without the SDK falling back.
    }
  }
  await setMode("ok");
  const res = await client.chat.completions.create(body(`after-trip-${Date.now()}`));
  check("circuit_open_falls_back", meta(res)?.servedBy === "provider-fallback", JSON.stringify(meta(res)));
});

console.log(`SMOKE_DONE failures=${failures}`);
process.exit(failures === 0 ? 0 : 1);
