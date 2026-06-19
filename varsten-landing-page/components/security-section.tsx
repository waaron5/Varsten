import {
  Activity,
  EyeOff,
  GitCommitVertical,
  Lock,
  ServerCog,
  ShieldCheck,
} from "lucide-react"

const items = [
  {
    icon: Activity,
    title: "Fail-open data plane",
    body: "If Varsten is ever degraded, traffic falls through to your providers untouched. Optimization never blocks a request.",
  },
  {
    icon: ShieldCheck,
    title: "Quality guardrails",
    body: "Every optimization is gated by regression floors. We hold output quality above a configurable threshold or we don't apply it.",
  },
  {
    icon: GitCommitVertical,
    title: "Versioned & auditable",
    body: "Pricing catalogs and policies are versioned, so every saving on the ledger ties back to the exact rules in effect.",
  },
  {
    icon: EyeOff,
    title: "Content storage is controlled",
    body: "The usage ledger stores metadata, not prompt or completion content. Cache and eval replay storage are explicit controls.",
  },
  {
    icon: Lock,
    title: "Scoped API keys",
    body: "Issue, rotate, and revoke Varsten keys per environment. Provider credentials stay encrypted and isolated.",
  },
  {
    icon: ServerCog,
    title: "Review ready",
    body: "Security questionnaire support and a DPA are available by request to clear procurement and legal.",
  },
]

export function SecuritySection() {
  return (
    <section id="security" className="border-b border-border bg-card">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            Security &amp; trust
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Optimization that earns its place in the request path.
          </h2>
          <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
            Sitting inline with production traffic is a serious responsibility.
            Varsten is engineered to be safe by default and transparent by
            design.
          </p>
        </div>

        <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => (
            <div key={item.title} className="bg-background p-6">
              <item.icon className="h-5 w-5 text-accent" />
              <h3 className="mt-4 text-base font-semibold text-foreground">
                {item.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
