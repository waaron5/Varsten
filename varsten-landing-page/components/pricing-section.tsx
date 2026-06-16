import { ArrowRight, Check } from "lucide-react"
import { ButtonLink } from "@/components/button-link"

const includes = [
  "Inline OpenAI / Anthropic / Gemini proxy",
  "Cache, routing, trimming & batching levers",
  "Quality guardrails with regression floors",
  "Verified savings ledger & attribution",
  "Versioned pricing catalog",
  "Fail-open data plane",
]

const ledger = [
  { label: "Monthly AI spend", value: "$25,000" },
  { label: "Gross savings (20%)", value: "$5,000", muted: false },
  { label: "Varsten fee (25% of savings)", value: "−$1,250", neg: true },
]

export function PricingSection() {
  return (
    <section id="pricing" className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            Pricing
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            You only pay a share of what we save you.
          </h2>
          <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
            No seat fees, no minimums to start. Varsten takes a percentage of
            verified savings — so the line item only grows when your costs go
            down.
          </p>
        </div>

        <div className="mx-auto mt-12 grid max-w-4xl gap-5 lg:grid-cols-2">
          {/* what's included */}
          <div className="rounded-xl border border-border bg-card p-7">
            <h3 className="text-lg font-semibold text-foreground">
              Performance plan
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Everything you need to safely cut spend.
            </p>
            <ul className="mt-6 space-y-3">
              {includes.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm text-foreground"
                >
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* example math */}
          <div className="flex flex-col rounded-xl border border-border bg-primary p-7 text-primary-foreground">
            <h3 className="text-lg font-semibold">Example month</h3>
            <p className="mt-1 text-sm text-primary-foreground/60">
              Conservative 20% savings scenario.
            </p>

            <dl className="mt-6 space-y-3">
              {ledger.map((row) => (
                <div
                  key={row.label}
                  className="flex items-center justify-between border-b border-primary-foreground/10 pb-3 text-sm"
                >
                  <dt className="text-primary-foreground/70">{row.label}</dt>
                  <dd
                    className={`font-medium tabular-nums ${row.neg ? "text-primary-foreground/70" : ""}`}
                  >
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-5 flex items-end justify-between">
              <div>
                <p className="text-sm text-primary-foreground/70">You keep</p>
                <p className="text-3xl font-semibold tracking-tight text-accent">
                  $3,750
                  <span className="text-base font-normal text-primary-foreground/60">
                    /mo
                  </span>
                </p>
              </div>
              <p className="text-right text-sm text-primary-foreground/70">
                ≈ $45,000
                <br />
                net / year
              </p>
            </div>

            <Button
              asChild
              size="lg"
              className="mt-6 w-full bg-accent text-accent-foreground hover:bg-accent/90"
            >
              <a href="https://app.varsten.ai/start">
                Start Free
                <ArrowRight className="ml-1 h-4 w-4" />
              </a>
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
