import type { Metadata } from "next";
import { START_OBSERVE_HREF } from "../site-links";
import { PageCta, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "About — Varsten",
  description: "Why Varsten is building measurement and optimization infrastructure for the cost of production AI.",
  path: "/about",
});

const principles = [
  ["Measure before changing", "A cost baseline and attribution should exist before production optimization decisions are made."],
  ["Keep the mechanism visible", "Teams should know which lever changed a request, why it was eligible, and what it saved."],
  ["Protect availability", "Production integrations need explicit failure behavior and a path back to the provider."],
  ["Make savings reviewable", "Engineering and finance should be able to reconcile the same baseline, actual spend, and evidence."],
] as const;

export default function AboutPage() {
  return (
    <SecondaryShell>
      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">About</h1>
        </div>
      </section>

      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 py-24 md:px-10 md:py-36">
          <p className="max-w-5xl text-[34px] font-medium leading-[1.2] tracking-[-0.025em] text-ink md:text-[56px]">Your business shouldn&apos;t have to ration AI usage. Scale your operations without scaling your bill.</p>
          <div className="mt-16 grid gap-10 border-t border-border pt-10 md:grid-cols-2 md:gap-20">
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">Why Varsten exists</p>
            <div className="grid gap-5 text-[16px] leading-8 text-ink-soft">
              <p>AI costs are unusually difficult to manage. Pricing changes by model and token type, one product action can trigger many provider calls, and the people operating the workload are often different from the people reviewing its spend.</p>
              <p>Varsten is building the measurement and optimization layer between those groups: visibility first, controlled savings second, and evidence throughout.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-border bg-muted">
        <div className="mx-auto max-w-[1400px] px-6 py-24 md:px-10 md:py-36">
          <div className="max-w-xl">
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">How we build</p>
            <h2 className="mt-4 text-[30px] font-semibold tracking-[-0.02em] text-ink md:text-[42px]">Four operating principles.</h2>
          </div>
          <div className="mt-14 grid gap-px border border-border bg-border md:grid-cols-2">
            {principles.map(([title, description], index) => (
              <article key={title} className="min-h-[250px] bg-white p-7 md:p-9">
                <p className="mono text-[10px] tracking-[0.24em] text-ink-soft">{String(index + 1).padStart(2, "0")}</p>
                <h3 className="mt-14 text-[21px] font-semibold text-ink">{title}</h3>
                <p className="mt-3 max-w-lg text-[14px] leading-6 text-ink-soft">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-border bg-background">
        <div className="mx-auto grid max-w-[1400px] gap-10 px-6 py-24 md:px-10 md:py-36 lg:grid-cols-[0.5fr_1fr] lg:gap-20">
          <div>
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">Company</p>
            <h2 className="mt-4 text-[30px] font-semibold tracking-[-0.02em] text-ink md:text-[42px]">Built deliberately.</h2>
          </div>
          <div className="max-w-2xl text-[16px] leading-8 text-ink-soft">
            <p>Varsten Systems, Inc. is an independent software company focused on AI cost infrastructure. The product is currently in public preview, with production rollouts kept narrow and explicit while customer evidence and operational maturity grow.</p>
            <p className="mt-5">We do not present roadmap deployments, certifications, or estimated savings as completed facts. That constraint is part of the product: cost controls are only useful when the evidence behind them can be trusted.</p>
          </div>
        </div>
      </section>

      <PageCta title="Start with a clear cost baseline." description="Observe mode shows where AI spend is going before anything in production changes." href={START_OBSERVE_HREF} label="Start a free audit" intent="observe" />
    </SecondaryShell>
  );
}
