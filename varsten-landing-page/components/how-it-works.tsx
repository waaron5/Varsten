import { Plug, Settings2, FileBadge } from "lucide-react"

const steps = [
  {
    n: "01",
    icon: Plug,
    title: "Connect",
    body: "Point your SDK base URL at Varsten and use a Varsten API key. No re-architecture, no SDK rewrite — your existing calls keep working.",
  },
  {
    n: "02",
    icon: Settings2,
    title: "Optimize",
    body: "Varsten applies cache, routing, trimming, batching, and model-swap policies only where guardrails confirm quality holds.",
  },
  {
    n: "03",
    icon: FileBadge,
    title: "Prove",
    body: "Every saving is attributed by lever, route, and measurement method — exported as a ledger your finance team can defend.",
  },
]

const codeLines: Array<Array<{ t: string; c?: string }>> = [
  [{ t: "client", c: "text-foreground" }, { t: " = " }, { t: "OpenAI", c: "text-accent" }, { t: "(" }],
  [
    { t: "    base_url", c: "text-foreground" },
    { t: "=" },
    { t: '"https://proxy.varsten.ai/v1"', c: "text-accent" },
    { t: "," },
  ],
  [
    { t: "    api_key", c: "text-foreground" },
    { t: "=os.environ[" },
    { t: '"VARSTEN_API_KEY"', c: "text-accent" },
    { t: "]," },
  ],
  [{ t: ")" }],
]

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="border-b border-border bg-card"
    >
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            How it works
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Three steps from spend to verified savings.
          </h2>
        </div>

        <div className="mt-12 grid gap-10 lg:grid-cols-2 lg:items-center">
          <ol className="space-y-3">
            {steps.map((step) => (
              <li
                key={step.n}
                className="flex gap-4 rounded-xl border border-border bg-background p-5"
              >
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary">
                  <step.icon className="h-5 w-5 text-accent" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">
                      {step.n}
                    </span>
                    <h3 className="text-lg font-semibold text-foreground">
                      {step.title}
                    </h3>
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          {/* code block */}
          <div className="overflow-hidden rounded-xl border border-border bg-primary shadow-xl shadow-foreground/10">
            <div className="flex items-center justify-between border-b border-primary-foreground/10 px-4 py-3">
              <span className="font-mono text-xs text-primary-foreground/60">
                main.py
              </span>
              <span className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-primary-foreground/20" />
                <span className="h-2.5 w-2.5 rounded-full bg-primary-foreground/20" />
                <span className="h-2.5 w-2.5 rounded-full bg-primary-foreground/20" />
              </span>
            </div>
            <pre className="overflow-x-auto p-5 font-mono text-sm leading-relaxed text-primary-foreground/85">
              <code>
                {codeLines.map((line, i) => (
                  <div key={i}>
                    {line.length === 0 ? (
                      "\u00A0"
                    ) : (
                      line.map((seg, j) => (
                        <span key={j} className={seg.c}>
                          {seg.t}
                        </span>
                      ))
                    )}
                  </div>
                ))}
              </code>
            </pre>
            <div className="border-t border-primary-foreground/10 px-5 py-3">
              <p className="text-xs text-primary-foreground/60">
                Drop-in replacement. Same SDKs, same calls — now metered,
                optimized, and proven.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
