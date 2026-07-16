import type { Metadata } from "next";
import { ENTERPRISE_FORM_HREF, START_OBSERVE_HREF, START_TRIAL_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { TrackedLink } from "@/components/varsten/TrackedLink";
import { NextStepCta } from "@/components/varsten/NextStepCta";
import { PricingFeatureList, PricingPlanBody, PricingPlanPrice, pricingToneClass } from "@/components/varsten/PricingPlanParts";
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
    priceNote: "",
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
    href: ENTERPRISE_FORM_HREF,
    event: "sales intent started" as const,
  },
] as const;

type PricingPlan = (typeof plans)[number];

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
        pricingToneClass(plan, "bg-ink text-primary-foreground", "bg-background"),
      ].join(" ")}
    >
      <div
          className={[
            "mono mb-8 flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.28em]",
            pricingToneClass(plan, "text-white/60", "text-ink-soft"),
          ].join(" ")}
        >
        <span>Plan · 0{index + 1}</span>
        <span className={pricingToneClass(plan, "text-white", "text-blueprint")}>{plan.tag}</span>
      </div>

      <h2
        className={[
          "text-[28px] font-medium tracking-[-0.01em]",
          pricingToneClass(plan, "text-white", "text-ink"),
        ].join(" ")}
      >
        {plan.name}
      </h2>

      <PricingPlanPrice
        plan={plan}
        wrapperClassName="mt-7 flex flex-wrap items-baseline gap-x-3 gap-y-2"
        priceClassName="text-[52px] font-medium leading-none tracking-[-0.03em] sm:text-[58px] md:text-[72px]"
        noteClassName="mono max-w-[150px] text-[11px] uppercase tracking-[0.22em]"
      />
      <PricingPlanBody plan={plan} />
      <PricingFeatureList
        plan={plan}
        itemClassName="flex min-w-0 items-start gap-3"
        textClassName="min-w-0 break-words"
        wrapperClassName="mono mt-8 grid min-w-0 gap-3 border-t pt-6 text-[11px] uppercase tracking-[0.12em] sm:text-[12px] sm:tracking-[0.18em]"
      />

      <div className="mt-auto pt-12">
        <TrackedLink
          href={plan.href}
          event="pricing plan selected"
          additionalEvents={[{ event: plan.event }]}
          eventProperties={{ plan: plan.id, cta: plan.cta }}
          className={[
            "inline-flex h-11 w-fit items-center gap-3 px-5 text-[13px] font-medium transition-opacity hover:opacity-90",
            pricingToneClass(plan, "bg-white text-ink", "bg-ink text-primary-foreground"),
          ].join(" ")}
        >
          {plan.cta}
          <span aria-hidden>→</span>
        </TrackedLink>
      </div>
    </article>
  );
}

export default function PricingPage() {
  return (
    <SecondaryShell>
      <section className="min-h-[calc(100svh-3.5rem)] border-b border-border bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            Pricing
          </h1>
          <div className="mt-10 grid min-w-0 grid-cols-1 border border-border md:mt-12 lg:grid-cols-3">
            {plans.map((plan, index) => (
              <PricingPlanCard key={plan.id} index={index} plan={plan} />
            ))}
          </div>
        </div>
      </section>

      <SavingsCalculator />

      <NextStepCta source="pricing_next_step" />
    </SecondaryShell>
  );
}
