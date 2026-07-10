import type { Metadata } from "next";
import { START_OBSERVE_HREF, START_TRIAL_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { TrackedLink } from "@/components/varsten/TrackedLink";
import { SavingsCalculator } from "@/components/varsten/pricing/SavingsCalculator";

export const metadata: Metadata = pageMetadata({
  title: "Pricing — Varsten",
  description:
    "Varsten pricing for observe-only monitoring, verified savings optimization, and enterprise AI cost governance.",
  path: "/pricing",
});

const plans = [
  {
    id: "observe",
    name: "Observe",
    price: "Free",
    priceNote: "no credit card",
    tag: "Audit mode",
    body: "See where your AI spend is going before changing production traffic.",
    features: [
      "Spend dashboard",
      "Pricing coverage checks",
      "Savings recommendations",
      "Metadata-only setup",
      "No production changes",
    ],
    cta: "Start observing",
    href: START_OBSERVE_HREF,
    event: "observe intent started" as const,
  },
  {
    id: "optimize",
    name: "Optimize",
    price: "25%",
    priceNote: "of savings",
    tag: "14-day trial",
    body: "Turn on approved savings levers and pay only from savings Varsten can prove.",
    features: [
      "Everything in Observe",
      "Production SDK setup",
      "Cache and routing controls",
      "Guardrails and rollback",
      "Proof reports",
    ],
    cta: "Start 14-day trial",
    href: START_TRIAL_HREF,
    event: "trial intent started" as const,
    highlighted: true,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "Custom",
    priceNote: "sales-led",
    tag: "Custom",
    body: "For teams that need procurement, security review, and a guided rollout.",
    features: [
      "Everything in Optimize",
      "Pilot planning",
      "Security review support",
      "Custom retention terms",
      "Procurement support",
    ],
    cta: "Talk to sales",
    href: "/enterprise",
    event: "sales intent started" as const,
  },
] as const;

type PricingPlan = (typeof plans)[number];

function toneClass(plan: PricingPlan, highlighted: string, defaultClass: string): string {
  return "highlighted" in plan && plan.highlighted ? highlighted : defaultClass;
}

function pricingCardBorder(index: number): string {
  if (index === plans.length - 1) return "";
  return "border-b border-border lg:border-b-0 lg:border-r";
}

function PricingPlanCard({ index, plan }: { index: number; plan: PricingPlan }) {
  return (
    <article
      className={[
        "relative flex min-h-[620px] min-w-0 flex-col p-6 sm:p-8 md:p-10 xl:p-12",
        pricingCardBorder(index),
        toneClass(plan, "bg-ink text-primary-foreground", "bg-background"),
      ].join(" ")}
    >
      <div
        className={[
          "mono mb-8 flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.28em]",
          toneClass(plan, "text-white/60", "text-ink-soft"),
        ].join(" ")}
      >
        <span>Plan · 0{index + 1}</span>
        <span className={toneClass(plan, "text-white", "text-blueprint")}>{plan.tag}</span>
      </div>

      <h2
        className={[
          "text-[28px] font-medium tracking-[-0.01em]",
          toneClass(plan, "text-white", "text-ink"),
        ].join(" ")}
      >
        {plan.name}
      </h2>

      <div className="mt-7 flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <span
          className={[
            "text-[52px] font-medium leading-none tracking-[-0.03em] sm:text-[58px] md:text-[72px]",
            toneClass(plan, "text-white", "text-ink"),
          ].join(" ")}
        >
          {plan.price}
        </span>
        <span
          className={[
            "mono max-w-[150px] text-[11px] uppercase tracking-[0.22em]",
            toneClass(plan, "text-white/60", "text-ink-soft"),
          ].join(" ")}
        >
          {plan.priceNote}
        </span>
      </div>

      <p
        className={[
          "mt-8 max-w-md text-[14px] leading-[1.65]",
          toneClass(plan, "text-white/70", "text-ink-soft"),
        ].join(" ")}
      >
        {plan.body}
      </p>

      <ul
        className={[
          "mono mt-8 grid min-w-0 gap-3 border-t pt-6 text-[11px] uppercase tracking-[0.12em] sm:text-[12px] sm:tracking-[0.18em]",
          toneClass(plan, "border-white/20 text-white", "border-border text-ink"),
        ].join(" ")}
      >
        {plan.features.map((feature) => (
          <li key={feature} className="flex min-w-0 items-start gap-3">
            <span className={toneClass(plan, "text-white/60", "text-blueprint")}>✓</span>
            <span className="min-w-0 break-words">{feature}</span>
          </li>
        ))}
      </ul>

      <div className="mt-auto pt-12">
        <TrackedLink
          href={plan.href}
          event="pricing plan selected"
          additionalEvents={[{ event: plan.event }]}
          eventProperties={{ plan: plan.id, cta: plan.cta }}
          className={[
            "inline-flex h-11 w-fit items-center gap-3 px-5 text-[13px] font-medium transition-opacity hover:opacity-90",
            toneClass(plan, "bg-white text-ink", "bg-ink text-primary-foreground"),
          ].join(" ")}
        >
          {plan.cta}
          <span aria-hidden>→</span>
        </TrackedLink>
      </div>
    </article>
  );
}

function PricingNextStep() {
  return (
    <section className="border-b border-border bg-background text-ink">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-8 px-6 py-12 md:flex-row md:items-center md:justify-between md:px-10">
        <div>
          <h2 className="max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]">
            Ready to start?
          </h2>
          <p className="mt-3 max-w-2xl text-[15px] leading-7 text-ink-soft">
            Automatically reduce your AI bill with cost optimization.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <TrackedLink
            href={START_TRIAL_HREF}
            event="trial intent started"
            eventProperties={{ cta: "Start a 14-day trial", source: "pricing_next_step" }}
            className="inline-flex h-11 items-center gap-3 bg-ink px-5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Start a 14-day trial
            <span aria-hidden>→</span>
          </TrackedLink>
          <TrackedLink
            href="/enterprise"
            event="sales intent started"
            eventProperties={{ cta: "Talk to sales", source: "pricing_next_step" }}
            className="inline-flex h-11 items-center gap-3 border border-ink px-5 text-[13px] font-medium text-ink transition-colors hover:bg-ink hover:text-primary-foreground"
          >
            Talk to sales
            <span aria-hidden>→</span>
          </TrackedLink>
        </div>
      </div>
    </section>
  );
}

export default function PricingPage() {
  return (
    <SecondaryShell>
      <section className="flex min-h-[calc(100svh-3.5rem)] flex-col justify-between border-b border-border bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            Pricing
          </h1>
        </div>
        <div className="mx-auto w-full max-w-[1400px] px-6 pb-12 md:px-10 md:pb-16">
          <div className="grid min-w-0 grid-cols-1 border border-border lg:grid-cols-3">
            {plans.map((plan, index) => (
              <PricingPlanCard key={plan.id} index={index} plan={plan} />
            ))}
          </div>
        </div>
      </section>

      <SavingsCalculator />

      <PricingNextStep />
    </SecondaryShell>
  );
}
