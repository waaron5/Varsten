import {
  CheckCircle2,
  FileCheck,
  GitBranch,
  Layers,
  ShieldHalf,
} from "lucide-react"

const signals = [
  "OpenAI-compatible proxy",
  "Anthropic-compatible proxy",
  "Gemini-compatible proxy",
  "Versioned pricing catalog",
  "Fail-open data plane",
  "Quality guardrails",
  "Verified savings ledger",
  "Optional metadata enrichment",
]

const badges = [
  { icon: ShieldHalf, label: "Security review ready" },
  { icon: FileCheck, label: "DPA available by request" },
  { icon: GitBranch, label: "Versioned & auditable" },
  { icon: Layers, label: "No data retention by default" },
]

export function TrustBar() {
  return (
    <section
      aria-label="Capabilities and trust signals"
      className="border-y border-border bg-card"
    >
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <p className="text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Built to drop into your existing AI stack
        </p>

        <div className="mt-5 flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
          {signals.map((signal) => (
            <span
              key={signal}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground"
            >
              <CheckCircle2 className="h-4 w-4 text-accent" />
              {signal}
            </span>
          ))}
        </div>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-3 border-t border-border pt-6">
          {badges.map((badge) => (
            <span
              key={badge.label}
              className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground"
            >
              <badge.icon className="h-3.5 w-3.5 text-foreground" />
              {badge.label}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}
