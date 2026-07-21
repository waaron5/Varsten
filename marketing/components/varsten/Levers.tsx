import { SectionIntro } from "./SectionIntro";

const levers = [
  {
    id: "01",
    name: "Smart Routing",
    body: "Sends each request to the most cost-effective AI model that can do the job well, deciding instantly for every prompt.",
    spec: "predicate → model tier",
  },
  {
    id: "02",
    name: "Semantic Cache",
    body: "Saves past AI answers and reuses them whenever a new request means the same thing, even if it's worded differently.",
    spec: "pgvector · TTL bound",
  },
  {
    id: "03",
    name: "Token Trim",
    body: "Cleans up prompts in real time by stripping out repeated text, extra whitespace, and unnecessary history before sending.",
    spec: "structural · policy gated",
  },
  {
    id: "04",
    name: "Prompt Compression",
    body: "Rewrites long system instructions into permanently shorter versions to cut token costs, requiring human review before going live.",
    spec: "eval/replay · hash-matched substitution",
  },
  {
    id: "05",
    name: "Model Downshift",
    body: "Uses test history to safely move routine tasks to cheaper models, testing changes on a small scale first with instant rollback.",
    spec: "eval-driven · canary window",
  },
  {
    id: "06",
    name: "Batching",
    body: "Groups non-urgent requests together in the background to process them at heavily discounted batch rates.",
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
            Traffic is sent through routing, cache, trim, downshift, and prompt
            compression mechanisms. Batching is a separate async workflow for
            non-urgent jobs. Each lever is auditable, individually togglable,
            and measured against the evidence appropriate to the workload.
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
