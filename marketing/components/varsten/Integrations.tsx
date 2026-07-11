import { useState } from "react";
import { SectionIntro } from "./SectionIntro";

const paths = [
  {
    id: "sdk",
    label: "Production SDK",
    tag: "Recommended",
    posture: "Optimized + fail-open",
    body: "The OpenAI wrapper sends healthy traffic through Varsten and falls back direct-to-provider on Varsten-origin failures before provider output starts. Your provider key stays local for fallback.",
    bullets: [
      "Direct provider fallback",
      "Per-request metadata supported",
      "Optimizations run where configured",
    ],
    code: `import { VarstenOpenAI, VarstenTrace } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  onFallback: (event) => {
    console.warn("varsten fallback", event.reasonCode);
  },
});

const trace = new VarstenTrace();

await client.chat.completions.create(
  {
    model: "gpt-4o-mini",
    messages,
  },
  {
    varsten: trace.metadata({
      feature: "support_agent",
      taskType: "classification.intent",
      customerId: "cust_123",
    }),
  },
);`,
  },
  {
    id: "eval",
    label: "Quick Eval",
    tag: "Fastest",
    posture: "Base URL trial",
    body: "A stock OpenAI client pointed at Varsten. Useful for low-risk evaluation traffic when you want the fastest proxy test. Not fail-open — use the SDK wrapper for production-critical routes.",
    bullets: [
      "Uses your Varsten vk_ key",
      "No wrapper package",
      "No direct fallback",
    ],
    code: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "https://api.varsten.ai/v1",
});

await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages,
});`,
  },
  {
    id: "meta",
    label: "Metadata Only",
    tag: "Strictest",
    posture: "Zero content egress",
    body: "The strictest security posture. Send async usage-event POSTs after your provider call. No provider key, prompt content, or completion content is sent to Varsten.",
    bullets: [
      "No provider key or content",
      "Async usage events",
      "Analysis only",
    ],
    code: `// after each provider call, outside the request path
await fetch("https://api.varsten.ai/v1/usage-events", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.VARSTEN_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    provider: "openai",
    model: "gpt-4o-mini",
    request_type: "chat_completion",
    feature: "support_agent",
    customer_id: "cust_123",
    environment: "production",
    input_tokens: usage.prompt_tokens,
    output_tokens: usage.completion_tokens,
    latency_ms: latencyMs,
    idempotency_key: requestId,
    occurred_at: new Date().toISOString(),
  }),
});`,
  },
] as const;

export function Integrations() {
  const [active, setActive] = useState<(typeof paths)[number]["id"]>("sdk");
  const current = paths.find((p) => p.id === active)!;

  return (
    <section id="integrations" className="border-b border-border">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <SectionIntro eyebrow="Section 03 · Integration" title="Match your security needs.">
          <p className="text-[16px] leading-[1.6] text-ink-soft">
            Three integration paths. Each preserves a different boundary
            between your infrastructure and the Varsten optimization layer —
            pick the one your security team already trusts.
          </p>
        </SectionIntro>

        <div className="grid gap-0 md:grid-cols-12">
          {/* Path selector */}
          <div className="border-b border-border md:col-span-4 md:border-b-0 md:border-r">
            {paths.map((p) => {
              const isActive = p.id === active;
              return (
                <button
                  key={p.id}
                  onClick={() => setActive(p.id)}
                  className={[
                    "relative block w-full border-b border-border p-6 text-left transition-colors md:p-8",
                    isActive ? "bg-muted" : "bg-background hover:bg-muted/60",
                  ].join(" ")}
                >
                  {isActive && (
                    <span className="absolute left-0 top-0 h-full w-[2px] bg-blueprint" />
                  )}
                  <div className="mono mb-3 flex items-center justify-between text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                    <span>Path 0{paths.indexOf(p) + 1}</span>
                    <span className={isActive ? "text-blueprint" : ""}>
                      {p.tag}
                    </span>
                  </div>
                  <div className="text-[18px] font-medium tracking-[-0.01em] text-ink">
                    {p.label}
                  </div>
                  <div className="mono mt-2 text-[11px] uppercase tracking-[0.2em] text-ink-soft">
                    {p.posture}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Detail */}
          <div className="md:col-span-8">
            <div className="border-b border-border p-8 md:p-12">
              <div className="mono mb-6 flex items-center gap-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                <span className="inline-block h-1.5 w-1.5 bg-blueprint" />
                {current.tag} · {current.posture}
              </div>
              <h3 className="text-[28px] font-medium tracking-[-0.02em] text-ink md:text-[36px]">
                {current.label}
              </h3>
              <p className="mt-6 max-w-2xl text-[15px] leading-[1.65] text-ink-soft">
                {current.body}
              </p>
              <ul className="mono mt-8 grid gap-2 text-[12px] uppercase tracking-[0.18em] text-ink">
                {current.bullets.map((b) => (
                  <li key={b} className="flex items-center gap-3">
                    <span className="text-blueprint">→</span>
                    {b}
                  </li>
                ))}
              </ul>
            </div>

            <div className="bg-[#0a0a0a] p-8 md:p-10">
              <div className="mono mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.28em] text-white/50">
                <span>example.ts</span>
                <span>v0.1.0</span>
              </div>
              <pre className="mono overflow-x-auto text-[13px] leading-[1.65] text-white/90">
                <code>{current.code}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
