import type { Metadata } from "next";
import { EARLY_ACCESS_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import { PageCta, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { FullShowcaseSection, SplitShowcaseSection } from "@/components/varsten/ShowcaseSection";

export const metadata: Metadata = pageMetadata({
  title: "Savings proof — Varsten",
  description:
    "How Varsten measures AI savings using traceable baselines, actual provider spend, quality gates, and measured overhead.",
  path: "/proof",
});

const evidenceMethods = [
  {
    number: "01",
    name: "Direct avoided cost",
    description: "Used when an exact provider call is eliminated, such as a verified cache hit.",
  },
  {
    number: "02",
    name: "Holdback A/B",
    description: "A controlled share keeps the original path so optimized and baseline behavior can be compared.",
  },
  {
    number: "03",
    name: "Replay evidence",
    description: "An approved request set estimates the counterfactual when a live holdback is not appropriate.",
  },
] as const;

const measurementSteps = [
  ["Tag", "Attach safe workload labels such as team, feature, provider, and model."],
  ["Measure", "Record actual usage, provider pricing, and the optimization applied."],
  ["Compare", "Use the evidence method approved for that lever and workload."],
  ["Reconcile", "Publish baseline, actual spend, overhead, and net savings separately."],
] as const;

const integrityChecks = [
  ["Pricing coverage", "Provider catalog or accepted contracted rates support the cost calculation."],
  ["Attribution coverage", "Savings remain connected to the team or feature responsible for the workload."],
  ["Quality acceptance", "Each lever is evaluated against the quality threshold appropriate to its risk."],
] as const;

export default function ProofPage() {
  return (
    <SecondaryShell>
      <section className="bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="max-w-5xl text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            How we measure savings
          </h1>
        </div>
      </section>

      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 pb-24 pt-8 md:px-10 md:pb-36 md:pt-12">
          <div className="max-w-3xl">
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">The calculation</p>
            <p className="mt-5 text-[28px] leading-[1.3] tracking-[-0.02em] text-ink md:text-[42px]">
              We separate what the workload would have cost from what it actually cost.
            </p>
          </div>

          <div className="mt-14 grid gap-px border border-border bg-border lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
            <div className="flex min-h-[220px] flex-col justify-between bg-white p-7 md:p-9">
              <span className="mono text-[10px] uppercase tracking-[0.25em] text-ink-soft">Baseline cost</span>
              <strong className="mt-12 text-[30px] font-medium tracking-[-0.02em] md:text-[40px]">Without optimization</strong>
            </div>
            <div className="hidden items-center justify-center bg-white px-3 text-[32px] font-light text-ink-soft lg:flex" aria-hidden="true">−</div>
            <div className="flex min-h-[220px] flex-col justify-between bg-white p-7 md:p-9">
              <span className="mono text-[10px] uppercase tracking-[0.25em] text-ink-soft">Actual cost</span>
              <strong className="mt-12 text-[30px] font-medium tracking-[-0.02em] md:text-[40px]">Provider spend + overhead</strong>
            </div>
            <div className="hidden items-center justify-center bg-white px-3 text-[32px] font-light text-ink-soft lg:flex" aria-hidden="true">=</div>
            <div className="flex min-h-[220px] flex-col justify-between bg-ink p-7 text-white md:p-9">
              <span className="mono text-[10px] uppercase tracking-[0.25em] text-white/55">Net savings</span>
              <strong className="mt-12 text-[30px] font-medium tracking-[-0.02em] md:text-[40px]">Customer benefit</strong>
            </div>
          </div>
        </div>
      </section>

      <SplitShowcaseSection eyebrow="01 · Evidence" title="Use the evidence that fits the lever." description="There is no single convenient formula applied to every optimization.">
          <div className="border-t border-border">
            {evidenceMethods.map((method) => (
              <article key={method.number} className="grid gap-4 border-b border-border py-7 sm:grid-cols-[64px_minmax(180px,0.55fr)_1fr] sm:gap-7">
                <span className="mono text-[10px] tracking-[0.24em] text-ink-soft">{method.number}</span>
                <h3 className="text-[18px] font-semibold text-ink">{method.name}</h3>
                <p className="max-w-xl text-[14px] leading-6 text-ink-soft">{method.description}</p>
              </article>
            ))}
          </div>
      </SplitShowcaseSection>

      <FullShowcaseSection eyebrow="02 · Process" title="From request to report.">
          <div className="mt-14 grid border border-border bg-border lg:grid-cols-4 lg:gap-px">
            {measurementSteps.map(([title, description], index) => (
              <article key={title} className="flex min-h-[260px] flex-col bg-white p-7 md:p-8">
                <span className="mono text-[10px] tracking-[0.24em] text-ink-soft">{String(index + 1).padStart(2, "0")}</span>
                <h3 className="mt-auto pt-12 text-[22px] font-semibold text-ink">{title}</h3>
                <p className="mt-3 text-[14px] leading-6 text-ink-soft">{description}</p>
              </article>
            ))}
          </div>
      </FullShowcaseSection>

      <SplitShowcaseSection eyebrow="03 · Integrity" title="Make the result reviewable.">
          <div className="grid gap-px border border-border bg-border sm:grid-cols-3">
            {integrityChecks.map(([title, description]) => (
              <article key={title} className="min-h-[260px] bg-white p-7">
                <span className="inline-flex h-5 w-5 items-center justify-center bg-ink text-[11px] text-white" aria-hidden="true">✓</span>
                <h3 className="mt-12 text-[18px] font-semibold text-ink">{title}</h3>
                <p className="mt-3 text-[13px] leading-6 text-ink-soft">{description}</p>
              </article>
            ))}
          </div>
      </SplitShowcaseSection>

      <PageCta
        title="Verify one lever before expanding."
        description="Start with a narrow workload where the baseline, fallback path, and savings ledger are easy to audit."
        href={EARLY_ACCESS_HREF}
        label="Request early access"
        intent="early-access"
      />
    </SecondaryShell>
  );
}
