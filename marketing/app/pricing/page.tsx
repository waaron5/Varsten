import type { Metadata } from "next";
import { CONTACT_EMAIL, START_OBSERVE_HREF, START_TRIAL_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import {
  CardGrid,
  InfoCard,
  NumberedList,
  PageCta,
  SecondarySection,
  SecondaryShell,
} from "@/components/varsten/SecondaryPage";
import { TrackedLink } from "@/components/varsten/TrackedLink";

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
    priceNote: "of verified savings",
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
    tag: "Security review",
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

      <SecondarySection
        title="How much could you save?"
        description="We should not put a broad savings percentage in the calculator until the number comes from measured simulations."
        tone="muted"
      >
        <CardGrid columns={3}>
          <InfoCard eyebrow="01" title="Replay real workload shapes">
            <p>
              Use support agents, agent loops, and high-variance chat as separate test sets. Each one should have a known
              amount of waste planted in it.
            </p>
          </InfoCard>
          <InfoCard eyebrow="02" title="Measure what Varsten captures">
            <p>
              Compare measured savings against the savings that were actually available. That gives us a capture rate,
              not a marketing guess.
            </p>
          </InfoCard>
          <InfoCard eyebrow="03" title="Publish conservative ranges">
            <p>
              The calculator should use low, typical, and high-fit ranges by workload type. If a workload has little to
              save, the calculator should say that too.
            </p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <SecondarySection
        title="How verified savings works"
        description="Pricing follows proof. Estimates can help you decide what to try, but they are not invoices."
      >
        <NumberedList
          items={[
            {
              title: "Agree the baseline",
              body: "Use the original provider path, a holdback group, or a replay set as the comparison.",
            },
            {
              title: "Measure the difference",
              body: "Compare what the request would have cost with what it actually cost after optimization.",
            },
            {
              title: "Bill only from verified savings",
              body: "Varsten's fee is capped at 25% of verified savings. If there are no verified savings, there is no savings fee.",
            },
          ]}
        />
      </SecondarySection>

      <SecondarySection title="Billing FAQ" description="The questions finance, engineering, and procurement usually ask.">
        <CardGrid columns={2}>
          <InfoCard title="What counts as verified savings?">
            <p>
              Savings supported by agreed evidence such as direct avoided cost, holdback comparison, replay evidence,
              and overhead subtraction.
            </p>
          </InfoCard>
          <InfoCard title="Do recommendations bill automatically?">
            <p>No. Recommendations and estimates are planning inputs, not invoices.</p>
          </InfoCard>
          <InfoCard title="Can procurement review the methodology?">
            <p>
              Yes. Enterprise rollouts should document the baseline, proof method, reporting period, and dispute path.
            </p>
          </InfoCard>
          <InfoCard title="Who should we contact for contracts?">
            <p>
              Email <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
            </p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <PageCta
        title="Start with one workload and a clean measurement boundary."
        description="The fastest path is usually Observe first, then one OpenAI workload with SDK fallback."
        href={START_OBSERVE_HREF}
        label="Start Observe"
        intent="observe"
      />
    </SecondaryShell>
  );
}
