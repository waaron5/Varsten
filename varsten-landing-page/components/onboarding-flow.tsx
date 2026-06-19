const steps = [
  "Create account",
  "Create project",
  "Generate Varsten API key",
  "Connect provider key",
  "Change SDK base URL",
  "Send first request",
  "Review spend and recommendations",
]

export function OnboardingFlow() {
  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
          <div>
            <p className="text-sm font-medium uppercase tracking-wider text-accent">
              Onboarding
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              Start Free goes straight into setup.
            </h2>
            <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
              The landing page should not trap buyers in a lead form. Free users
              enter the app, create a project, and install Varsten against real
              traffic.
            </p>
          </div>

          <ol className="grid gap-3 sm:grid-cols-2">
            {steps.map((step, index) => (
              <li
                key={step}
                className="flex items-center gap-4 rounded-xl border border-border bg-card p-4"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary font-mono text-xs font-semibold text-accent">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="text-sm font-medium text-foreground">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}
