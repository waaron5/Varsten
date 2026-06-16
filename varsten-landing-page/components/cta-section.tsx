import { ArrowRight, CalendarClock } from "lucide-react"
import { Button } from "@/components/ui/button"

export function CtaSection() {
  return (
    <section id="book-call" className="bg-background">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="overflow-hidden rounded-2xl border border-border bg-primary px-6 py-14 text-center sm:px-12">
          <h2 className="mx-auto max-w-2xl text-balance text-3xl font-semibold tracking-tight text-primary-foreground sm:text-4xl">
            Cut AI costs safely, then prove every dollar saved.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-pretty text-lg leading-relaxed text-primary-foreground/70">
            Point your traffic at Varsten in minutes, or let our team handle a
            white-glove setup against your real workload.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button
              asChild
              size="lg"
              className="w-full bg-accent text-accent-foreground hover:bg-accent/90 sm:w-auto"
            >
              <a href="https://app.varsten.ai/start">
                Start Free
                <ArrowRight className="ml-1 h-4 w-4" />
              </a>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="w-full border-primary-foreground/20 bg-transparent text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground sm:w-auto"
            >
              <a href="#book-call">
                <CalendarClock className="mr-1 h-4 w-4" />
                Book setup call
              </a>
            </Button>
          </div>
          <p className="mt-5 text-sm text-primary-foreground/50">
            No credit card to start · Cancel any time · You keep most of the
            savings
          </p>
        </div>
      </div>
    </section>
  )
}
