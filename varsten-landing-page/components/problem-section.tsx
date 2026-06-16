import { LineChart, ShieldAlert, ReceiptText } from "lucide-react"

const cards = [
  {
    icon: LineChart,
    title: "Spend is growing faster than revenue",
    body: "AI usage compounds with every feature you ship. Without controls, inference becomes one of your largest and least predictable line items.",
  },
  {
    icon: ShieldAlert,
    title: "Model changes risk quality regressions",
    body: "Swapping models or trimming context to save money can quietly degrade output. Manual optimization is slow and dangerous at scale.",
  },
  {
    icon: ReceiptText,
    title: "Finance can't trust vague estimates",
    body: '"We think we saved ~20%" does not survive a board review. Teams need savings attributed by lever, route, and measurement method.',
  },
]

export function ProblemSection() {
  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            The problem
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            AI spend is becoming COGS.
          </h2>
          <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
            Most teams can see the bill. Very few have a safe way to reduce it —
            and even fewer can prove the reduction to finance.
          </p>
        </div>

        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {cards.map((card) => (
            <div
              key={card.title}
              className="rounded-xl border border-border bg-card p-6"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-secondary">
                <card.icon className="h-5 w-5 text-foreground" />
              </div>
              <h3 className="mt-5 text-lg font-semibold text-foreground">
                {card.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {card.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
