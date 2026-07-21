import type { Metadata } from "next";
import Image from "next/image";
import { EARLY_ACCESS_HREF, START_OBSERVE_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import { PageCta, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { TrackedLink } from "@/components/varsten/TrackedLink";

export const metadata: Metadata = pageMetadata({
  title: "Product tour — Varsten",
  description: "See how Varsten surfaces AI spend, controls cost-saving automations, and documents measured savings.",
  path: "/product-tour",
});

const tourStops = [
  {
    number: "01",
    eyebrow: "Observe",
    title: "See the cost picture in one place.",
    body: "Track actual spend, baseline cost, gross savings, and net realized savings from the same dashboard. Breakdowns connect the financial view to the teams, features, and optimization methods driving it.",
    image: "/product-tour/dashboard.png",
    alt: "Varsten dashboard showing demo spend, baseline cost, savings metrics, and a daily savings chart",
  },
  {
    number: "02",
    eyebrow: "Optimize",
    title: "Control every savings method.",
    body: "Review the status and measured impact of caching, model downshift, batching, token trimming, routing, and compression. Each automation remains a visible project-level control rather than a hidden black box.",
    image: "/product-tour/automation.png",
    alt: "Varsten automation screen showing demo savings controls and measured savings by method",
  },
  {
    number: "03",
    eyebrow: "Prove",
    title: "Separate spend, savings, and fees.",
    body: "The savings ledger keeps the counterfactual baseline, actual provider spend, gross savings, Varsten fee, and net customer benefit distinct so the result can be reviewed instead of merely asserted.",
    image: "/product-tour/savings-proof.png",
    alt: "Varsten savings proof screen showing demo counterfactual spend, actual spend, gross savings, and net savings",
  },
] as const;

function ProductFrame({ alt, image }: { alt: string; image: string }) {
  return (
    <div className="overflow-hidden border border-border bg-white shadow-[0_22px_70px_rgba(17,17,17,0.10)]">
      <div className="flex items-center justify-between border-b border-border bg-muted px-4 py-3">
        <div className="flex gap-1.5" aria-hidden="true">
          <span className="h-2 w-2 rounded-full bg-ink/20" />
          <span className="h-2 w-2 rounded-full bg-ink/20" />
          <span className="h-2 w-2 rounded-full bg-ink/20" />
        </div>
        <span className="mono text-[9px] uppercase tracking-[0.22em] text-ink-soft">Demo data</span>
      </div>
      <Image
        src={image}
        alt={alt}
        width={1440}
        height={1000}
        sizes="(max-width: 768px) 100vw, 1200px"
        className="h-auto w-full"
      />
    </div>
  );
}

export default function ProductTourPage() {
  return (
    <SecondaryShell>
      <section className="border-b border-border bg-ink text-white">
        <div className="mx-auto max-w-[1400px] px-6 py-16 md:px-10 md:py-24">
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-white/50">Product tour · Demo workspace</p>
          <div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.48fr)] lg:items-end">
            <h1 className="max-w-5xl text-[46px] font-semibold leading-[1.02] tracking-[-0.03em] md:text-[78px]">
              See what happens after your AI bill enters Varsten.
            </h1>
            <div>
              <p className="text-[17px] leading-8 text-white/65">
                A guided look at the real product interface—from visibility, to controlled optimization, to savings proof.
              </p>
              <p className="mono mt-5 border-t border-white/15 pt-4 text-[10px] uppercase leading-5 tracking-[0.2em] text-white/45">
                Screens show fictional, illustrative data. No customer or production account data is displayed.
              </p>
            </div>
          </div>
        </div>
      </section>

      {tourStops.map((stop, index) => (
        <section key={stop.number} className={`border-b border-border ${index % 2 ? "bg-muted" : "bg-background"}`}>
          <div className="mx-auto max-w-[1400px] px-6 py-14 md:px-10 md:py-20">
            <div className="grid gap-6 md:grid-cols-[100px_minmax(0,1fr)] md:items-start">
              <p className="mono text-[12px] uppercase tracking-[0.28em] text-blueprint">{stop.number}</p>
              <div className="max-w-3xl">
                <p className="mono text-[10px] uppercase tracking-[0.24em] text-ink-soft">{stop.eyebrow}</p>
                <h2 className="mt-3 text-[32px] font-semibold leading-tight tracking-[-0.02em] text-ink md:text-[48px]">
                  {stop.title}
                </h2>
                <p className="mt-5 text-[16px] leading-7 text-ink-soft">{stop.body}</p>
              </div>
            </div>
            <div className="mt-10 md:mt-14">
              <ProductFrame image={stop.image} alt={stop.alt} />
            </div>
          </div>
        </section>
      ))}

      <PageCta
        title="Start with your own cost baseline."
        description="Run the free audit first, or request early access when you are ready to evaluate optimization controls."
        href={START_OBSERVE_HREF}
        label="Start a free audit"
        intent="observe"
      />
      <section className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-6 py-10 md:flex-row md:items-center md:justify-between md:px-10">
          <p className="text-[14px] leading-6 text-ink-soft">Want to evaluate Optimize with a real workload?</p>
          <TrackedLink
            href={EARLY_ACCESS_HREF}
            event="early access intent started"
            eventProperties={{ cta: "Request early access", source: "product_tour" }}
            className="inline-flex h-11 w-fit items-center gap-3 border border-ink px-5 text-[13px] font-medium text-ink transition-colors hover:bg-ink hover:text-white"
          >
            Request early access <span aria-hidden>→</span>
          </TrackedLink>
        </div>
      </section>
    </SecondaryShell>
  );
}
