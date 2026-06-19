import { BarChart3, BadgeDollarSign, ShieldCheck } from "lucide-react"

const pillars = [
  {
    icon: BarChart3,
    title: "Observe",
    body: "Measure AI spend by model, route, feature, customer, and team before any optimization changes production behavior.",
    items: [
      "Usage ledger",
      "Spend drivers",
      "Pricing trust checks",
      "Metadata-based attribution",
    ],
  },
  {
    icon: ShieldCheck,
    title: "Optimize",
    body: "Apply cost-saving policies only where the quality bar holds, with live controls for each lever.",
    items: [
      "Cache and routing",
      "Token trimming",
      "Batch routing",
      "Eval-gated model swaps",
    ],
  },
  {
    icon: BadgeDollarSign,
    title: "Prove",
    body: "Show finance what changed, how savings were measured, and what the customer keeps after Varsten's fee.",
    items: [
      "Verified savings ledger",
      "Gross and net savings",
      "Attribution by lever",
      "Data quality coverage",
    ],
  },
]

export function ProductPillars() {
  return (
    <section className="border-b border-border bg-card">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            Product
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            One loop: observe, optimize, prove.
          </h2>
          <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
            Varsten is not another passive analytics dashboard. It is the engine
            that finds savings, applies the safe ones, and keeps the evidence.
          </p>
        </div>

        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          {pillars.map((pillar) => (
            <article
              key={pillar.title}
              className="rounded-xl border border-border bg-background p-6"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-secondary">
                <pillar.icon className="h-5 w-5 text-accent" />
              </div>
              <h3 className="mt-5 text-xl font-semibold text-foreground">
                {pillar.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {pillar.body}
              </p>
              <ul className="mt-5 space-y-2 border-t border-border pt-5">
                {pillar.items.map((item) => (
                  <li
                    key={item}
                    className="flex items-center justify-between gap-4 text-sm"
                  >
                    <span className="text-muted-foreground">{item}</span>
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
