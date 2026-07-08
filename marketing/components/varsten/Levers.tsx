import { SectionIntro } from "./SectionIntro";

const levers = [
  {
    id: "01",
    name: "Smart Routing",
    body: "Per-request predicates route traffic to the lowest-cost model that clears your specific quality bar. Rules compile to a routing table evaluated in constant time on every call.",
    spec: "predicate → model tier",
  },
  {
    id: "02",
    name: "Semantic Cache",
    body: "Fast exact and semantic matching utilizing pgvector, model-scoped constraints, and strict TTL bounds. Cache keys are namespaced by model, temperature, and tool schema.",
    spec: "pgvector · TTL bound",
  },
  {
    id: "03",
    name: "Token Trim",
    body: "A conservative hot-path transform can keep recent turns, remove exact duplicate text messages, and collapse excess whitespace. It avoids inline LLM summarization and passes structured content through untouched.",
    spec: "structural · policy gated",
  },
  {
    id: "04",
    name: "Prompt Compression",
    body: "An off-path LLM generates optimized, permanently shorter versions of your stable system prompts. Runs through an eval/replay gate requiring named human approval before the proxy substitutes it via exact hash-matching.",
    spec: "eval/replay · hash-matched substitution",
  },
  {
    id: "05",
    name: "Model Downshift",
    body: "Continuously analyzes historical evals to safely shift stable production workloads to cheaper model tiers. Downshifts are staged with a canary window and instant rollback.",
    spec: "eval-driven · canary window",
  },
  {
    id: "06",
    name: "Batching",
    body: "For non-urgent OpenAI workloads, clients stage JSONL input and submit it through Varsten's /v1/batches mirror. The batch data plane polls, finalizes output, and records batch-price savings off the inline path.",
    spec: "async API · off-path",
  },
];

type Lever = (typeof levers)[number];

const leverBorderClasses = [
  "border-b md:border-r lg:border-r",
  "border-b md:border-r-0 lg:border-r",
  "border-b md:border-r lg:border-r-0",
  "border-b md:border-r-0 lg:border-r lg:border-b-0",
  "border-b md:border-b-0 md:border-r lg:border-r lg:border-b-0",
  "border-b md:border-b-0 md:border-r-0 lg:border-r-0 lg:border-b-0",
];

function leverBorderClass(index: number): string {
  return leverBorderClasses[index] ?? "border-b";
}

function LeverCard({ index, lever }: { index: number; lever: Lever }) {
  return (
    <article className={`group relative border-border p-8 md:p-10 ${leverBorderClass(index)}`}>
      <div className="mono mb-8 flex items-center justify-between text-[11px] uppercase tracking-[0.28em] text-ink-soft">
        <span>{lever.id}</span>
        <span className="text-blueprint">●</span>
      </div>
      <h3 className="text-[22px] font-medium tracking-[-0.01em] text-ink">
        {lever.name}
      </h3>
      <p className="mt-4 text-[14px] leading-[1.6] text-ink-soft">
        {lever.body}
      </p>
      <div className="mono mt-8 border-t border-border pt-4 text-[10px] uppercase tracking-[0.28em] text-ink">
        {lever.spec}
      </div>
    </article>
  );
}

export function Levers() {
  return (
    <section id="levers" className="border-b border-border">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <SectionIntro eyebrow="Section 02 · Mechanisms" title="Six optimization levers, clearly scoped.">
          <p className="text-[16px] leading-[1.6] text-ink-soft">
            Inline traffic can use routing, cache, trim, downshift, and prompt
            compression policies. Batching is a separate async workflow for
            non-urgent jobs. Each lever is auditable, individually togglable,
            and shipped with instrumentation.
          </p>
        </SectionIntro>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {levers.map((l, i) => (
            <LeverCard key={l.id} index={i} lever={l} />
          ))}
        </div>
      </div>
    </section>
  );
}
