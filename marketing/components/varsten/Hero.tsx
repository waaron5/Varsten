import { FlowDiagram } from "./FlowDiagram";
import { EARLY_ACCESS_HREF, START_OBSERVE_HREF } from "@/app/site-links";
import { TrackedLink } from "./TrackedLink";

export function Hero() {
  return (
    <section id="top" className="relative border-b border-border">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <div className="grid min-h-[calc(100svh-3.5rem)] items-center gap-16 py-16 md:py-20 lg:grid-cols-12 lg:gap-12">
          <div className="lg:col-span-7">
            <div className="mono mb-8 flex items-center gap-3 text-[11px] uppercase tracking-[0.28em] text-ink-soft">
              <span className="inline-block h-1.5 w-1.5 bg-blueprint" />
              LLM cost optimization · public preview
            </div>

            <h1 className="text-[44px] font-medium leading-[1.02] tracking-[-0.03em] text-ink sm:text-[64px] md:text-[80px] lg:text-[92px]">
              Cut your AI bill
              <br />
              without changing
              <br />
              your code.
            </h1>

            <p className="mt-10 max-w-xl text-[17px] leading-[1.55] text-ink-soft">
              A drop-in optimization engine that captures, routes, and reprices
              your LLM traffic in real-time.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-3">
              <TrackedLink
                href={EARLY_ACCESS_HREF}
                event="early access intent started"
                eventProperties={{ cta: "Request early access", source: "hero" }}
                className="inline-flex h-11 items-center gap-3 bg-ink px-5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
              >
                Request early access
                <span aria-hidden className="mono text-[11px] opacity-70">
                  Founder-led
                </span>
              </TrackedLink>
              <TrackedLink
                href={START_OBSERVE_HREF}
                event="free audit started"
                eventProperties={{ cta: "Start a free audit", source: "hero" }}
                className="inline-flex h-11 items-center gap-2 border border-ink px-5 text-[13px] font-medium text-ink transition-colors hover:bg-ink hover:text-primary-foreground"
              >
                Start a free audit
              </TrackedLink>
            </div>

            <dl className="mono mt-16 grid max-w-lg grid-cols-3 gap-x-6 border-t border-border pt-6 text-[11px] uppercase tracking-[0.2em] text-ink-soft">
              {[
                ["6", "levers"],
                ["3", "Integrations"],
                ["25%", "Pay from savings"],
              ].map(([k, v]) => (
                <div key={v}>
                  <dt className="mb-2 text-ink-soft">{v}</dt>
                  <dd className="text-[22px] font-normal tracking-tight text-ink">
                    {k}
                  </dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="lg:col-span-5">
            <FlowDiagram />
          </div>
        </div>
      </div>
    </section>
  );
}
