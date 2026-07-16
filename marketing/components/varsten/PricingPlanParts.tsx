export type PricingTonePlan = {
  body: string;
  features: readonly string[];
  highlighted?: boolean;
  price: string;
  priceNote: string;
};

export function pricingToneClass(plan: PricingTonePlan, highlighted: string, defaultClass: string): string {
  return plan.highlighted ? highlighted : defaultClass;
}

export function PricingPlanPrice({
  noteClassName = "mono text-[11px] uppercase tracking-[0.22em]",
  plan,
  priceClassName = "text-[56px] font-medium leading-none tracking-[-0.03em] md:text-[72px]",
  wrapperClassName = "mt-6 flex items-baseline gap-3",
}: {
  noteClassName?: string;
  plan: PricingTonePlan;
  priceClassName?: string;
  wrapperClassName?: string;
}) {
  return (
    <div className={wrapperClassName}>
      <span className={[priceClassName, pricingToneClass(plan, "text-white", "text-ink")].join(" ")}>
        {plan.price}
      </span>
      <span className={[noteClassName, pricingToneClass(plan, "text-white/60", "text-ink-soft")].join(" ")}>
        {plan.priceNote}
      </span>
    </div>
  );
}

export function PricingPlanBody({ plan }: { plan: PricingTonePlan }) {
  return (
    <p className={["mt-8 max-w-md text-[14px] leading-[1.65]", pricingToneClass(plan, "text-white/70", "text-ink-soft")].join(" ")}>
      {plan.body}
    </p>
  );
}

export function PricingFeatureList({
  itemClassName = "flex items-start gap-3",
  plan,
  textClassName,
  wrapperClassName = "mono mt-8 grid gap-3 border-t pt-6 text-[12px] uppercase tracking-[0.18em]",
}: {
  itemClassName?: string;
  plan: PricingTonePlan;
  textClassName?: string;
  wrapperClassName?: string;
}) {
  return (
    <ul className={[wrapperClassName, pricingToneClass(plan, "border-white/20 text-white", "border-border text-ink")].join(" ")}>
      {plan.features.map((feature) => (
        <li key={feature} className={itemClassName}>
          <span className={pricingToneClass(plan, "text-white/60", "text-blueprint")}>✓</span>
          <span className={textClassName}>{feature}</span>
        </li>
      ))}
    </ul>
  );
}
