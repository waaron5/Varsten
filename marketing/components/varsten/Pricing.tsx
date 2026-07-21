import { EARLY_ACCESS_HREF, ENTERPRISE_FORM_HREF, START_OBSERVE_HREF } from "@/app/site-links";
import { SectionIntro } from "./SectionIntro";
import { TrackedLink } from "./TrackedLink";
import { PricingFeatureList, PricingPlanBody, PricingPlanPrice, pricingToneClass } from "./PricingPlanParts";

const plans = [
  {
    id: "observe",
    name: "Observe",
    price: "Free",
    priceNote: "no credit card",
    tag: "Audit mode",
    body: "Connect via Quick Eval or Metadata Only to audit your live traffic and map out estimated savings, with no behavior-changing optimization applied.",
    features: [
      "Monitor AI spend",
      "100k requests/month",
      "Savings recommendations",
      "Quick Eval or Metadata",
      "No credit card required",
    ],
    cta: "Start a free audit",
    href: START_OBSERVE_HREF,
    event: "free audit started" as const,
  },
  {
    id: "performance",
    name: "Optimize",
    price: "25%",
    priceNote: "of verified savings",
    tag: "Early access",
    body: "Unlocks the optimization engine: inline routing, cache, trim, compression, and downshift, plus async batching for eligible jobs. Pricing is capped at 25% of verified savings.",
    features: [
      "Everything in free + ",
      "Automated cost savings",
      "Unlimited requests/month",
      "Production-safe SDK integration",
      "Controls, guardrails, rollback",
    ],
    cta: "Request early access",
    highlighted: true,
    href: EARLY_ACCESS_HREF,
    event: "early access intent started" as const,
  },
];

type Plan = (typeof plans)[number];

function planCardBorder(index: number): string {
  return index === 0 ? "border-b border-border md:border-b-0 md:border-r" : "";
}

function PricingCard({ index, plan }: { index: number; plan: Plan }) {
  const cardClass = [
    "relative p-8 md:p-12",
    planCardBorder(index),
    pricingToneClass(plan, "bg-ink text-primary-foreground", "bg-background"),
  ].join(" ");

  return (
    <div className={cardClass}>
      <div
          className={[
            "mono mb-8 flex items-center justify-between text-[10px] uppercase tracking-[0.28em]",
            pricingToneClass(plan, "text-white/60", "text-ink-soft"),
          ].join(" ")}
        >
        <span>Plan · 0{index + 1}</span>
        <span className={pricingToneClass(plan, "text-white", "text-blueprint")}>
          {plan.tag}
        </span>
      </div>

      <h3
        className={[
          "text-[26px] font-medium tracking-[-0.01em]",
          pricingToneClass(plan, "text-white", "text-ink"),
        ].join(" ")}
      >
        {plan.name}
      </h3>

      <PricingPlanPrice plan={plan} />
      <PricingPlanBody plan={plan} />
      <PricingFeatureList plan={plan} />

      <TrackedLink
        href={plan.href}
        event={plan.event}
        eventProperties={{ cta: plan.cta, plan: plan.id, source: "homepage_pricing" }}
        className={[
          "mt-12 inline-flex h-11 items-center gap-3 px-5 text-[13px] font-medium transition-opacity hover:opacity-90",
          pricingToneClass(plan, "bg-white text-ink", "bg-ink text-primary-foreground"),
        ].join(" ")}
      >
        {plan.cta}
        <span aria-hidden>→</span>
      </TrackedLink>
    </div>
  );
}

export function Pricing() {
  return (
    <section id="pricing" className="border-b border-border">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <SectionIntro eyebrow="Section 04 · Pricing" title="Verified savings, or you pay nothing.">
          <p className="text-[16px] leading-[1.6] text-ink-soft">
            Opportunity estimates are free. Paid savings use an accepted evidence method—such as direct avoided cost, holdback comparison,
            or approved replay—with applicable overhead subtracted before fees are calculated.
          </p>
          <div className="mono mt-6 border-t border-border pt-4 text-[11px] uppercase tracking-[0.24em] text-ink">
            Fee &lt; Savings · always
          </div>
        </SectionIntro>

        <div id="trial" className="grid gap-0 md:grid-cols-2">
          {plans.map((p, i) => (
            <PricingCard key={p.id} index={i} plan={p} />
          ))}
        </div>

        <div className="border-t border-border p-8 md:flex md:items-center md:justify-between md:gap-10 md:p-12">
          <div className="md:max-w-md">
            <div className="mono mb-8 flex items-center gap-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
              <span>Plan · 03</span>
              <span className="text-blueprint">Custom</span>
            </div>
            <h3 className="text-[26px] font-medium tracking-[-0.01em] text-ink">
              Enterprise
            </h3>
            <p className="mt-6 text-[14px] leading-[1.65] text-ink-soft">
              For custom pricing that doesn&apos;t scale with your bill,
              <br />
              we negotiate a rate and fee cap.
            </p>
          </div>

          <div className="mt-8 md:mt-0">
            <TrackedLink
              href={ENTERPRISE_FORM_HREF}
              event="enterprise call intent started"
              eventProperties={{ cta: "Discuss an enterprise pilot", source: "homepage_pricing" }}
              className="inline-flex h-11 shrink-0 items-center gap-3 border border-ink px-5 text-[13px] font-medium text-ink transition-colors hover:bg-ink hover:text-primary-foreground"
            >
              Discuss an enterprise pilot
              <span aria-hidden>→</span>
            </TrackedLink>
          </div>
        </div>
      </div>
    </section>
  );
}
