import { ArrowRight, Check } from "lucide-react"
import { ButtonLink } from "@/components/button-link"
import { Dashboard } from "@/components/dashboard"

const heroPoints = [
  "Reduces AI spend",
  "Keeps output quality safe",
  "Proves every dollar saved",
]

export function Hero() {
  return (
    <section id="product" className="relative overflow-hidden">
      <div className="mx-auto max-w-7xl px-4 pb-12 pt-16 sm:px-6 sm:pb-16 sm:pt-20 lg:px-8 lg:pt-24">
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            The financial control plane for AI spend
          </span>

          <h1 className="mx-auto mt-6 max-w-72 text-balance text-3xl font-semibold tracking-tight text-foreground sm:max-w-none sm:text-5xl lg:text-6xl">
            <span className="block sm:inline">Reduce AI spend</span>{" "}
            <span className="block sm:inline">without sacrificing</span>{" "}
            <span className="block sm:inline">quality.</span>
          </h1>

          <p className="mx-auto mt-5 max-w-72 text-pretty text-base leading-relaxed text-muted-foreground sm:max-w-2xl sm:text-lg">
            Varsten sits in front of your AI providers, applies safe cost
            optimizations, and proves the savings with a ledger your finance
            team can trust.
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <ButtonLink
              size="lg"
              variant="primary"
              href="https://app.varsten.ai/start"
              className="w-72 max-w-full sm:w-auto"
            >
              Start Free
              <ArrowRight />
            </ButtonLink>
            <ButtonLink
              size="lg"
              variant="outline"
              href="mailto:mail@varsten.ai?subject=Varsten%20setup%20call"
              className="w-72 max-w-full sm:w-auto"
            >
              Book setup call
            </ButtonLink>
          </div>

          <ul className="mt-7 flex flex-col items-center justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground sm:flex-row">
            {heroPoints.map((point) => (
              <li key={point} className="flex items-center gap-1.5">
                <Check className="h-4 w-4 text-accent" />
                {point}
              </li>
            ))}
          </ul>
        </div>

        <div className="mx-auto mt-14 max-w-5xl">
          <Dashboard />
        </div>
      </div>
    </section>
  )
}
