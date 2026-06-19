import {
  Archive,
  Braces,
  GitBranch,
  Layers3,
  Route,
} from "lucide-react"

const levers = [
  {
    icon: Route,
    title: "Smart routing",
    body: "Send each request to the lowest-cost model that clears the route's quality bar.",
  },
  {
    icon: Layers3,
    title: "Semantic cache",
    body: "Reuse safe repeat responses instead of paying for another model call.",
  },
  {
    icon: Braces,
    title: "Token trim",
    body: "Remove redundant prompt and context tokens before the provider call.",
  },
  {
    icon: GitBranch,
    title: "Cheaper model",
    body: "Move whole workloads down a model tier after evals prove quality holds.",
  },
  {
    icon: Archive,
    title: "Batching",
    body: "Route non-urgent jobs through batch APIs to capture lower provider pricing.",
  },
]

export function SavingsLevers() {
  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            Savings engine
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Five levers, one measured savings ledger.
          </h2>
          <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
            Each recommendation maps to a specific lever, a route, a measured
            or estimated dollar impact, and a quality control.
          </p>
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {levers.map((lever) => (
            <article
              key={lever.title}
              className="rounded-xl border border-border bg-card p-5"
            >
              <lever.icon className="h-5 w-5 text-accent" />
              <h3 className="mt-4 text-base font-semibold text-foreground">
                {lever.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {lever.body}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
