const faqs = [
  {
    q: "Does Varsten replace my AI provider?",
    a: "No. Varsten sits between your application and providers such as OpenAI, Anthropic, and Gemini.",
  },
  {
    q: "Can I start without changing production behavior?",
    a: "Yes. Free is observe-only, so Varsten meters traffic and surfaces recommendations before you enable optimization.",
  },
  {
    q: "What happens if Varsten is unavailable?",
    a: "The data plane is designed to fail open. Requests pass through to the original provider instead of blocking production traffic.",
  },
  {
    q: "How does billing work?",
    a: "Free is $0. Performance charges 25% of verified savings, so the customer keeps the remaining 75%.",
  },
  {
    q: "Do you store prompts and completions?",
    a: "The usage ledger stores metadata, not prompt or completion content. Cache and eval replay storage should be explicit and controlled.",
  },
  {
    q: "How are savings proven?",
    a: "Savings are attributed by lever, route, pricing source, and measurement method, with eval or holdback evidence where available.",
  },
]

export function FaqSection() {
  return (
    <section className="border-b border-border bg-card">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-sm font-medium uppercase tracking-wider text-accent">
            FAQ
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            The questions a serious buyer asks first.
          </h2>
        </div>

        <div className="mx-auto mt-12 grid max-w-5xl gap-4 md:grid-cols-2">
          {faqs.map((faq) => (
            <article
              key={faq.q}
              className="rounded-xl border border-border bg-background p-5"
            >
              <h3 className="text-base font-semibold text-foreground">
                {faq.q}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {faq.a}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
