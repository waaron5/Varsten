import { ENTERPRISE_FORM_HREF, START_TRIAL_HREF } from "@/app/site-links";
import { TrackedLink } from "@/components/varsten/TrackedLink";

function shellClass(invert: boolean | undefined): string {
  return ["border-b border-border", invert ? "bg-ink text-primary-foreground" : "bg-background text-ink"].join(" ");
}

function mutedTextClass(invert: boolean | undefined): string {
  return ["mt-3 max-w-2xl text-[15px] leading-7", invert ? "text-white/70" : "text-ink-soft"].join(" ");
}

function primaryCtaClass(invert: boolean | undefined): string {
  return [
    "inline-flex h-11 items-center gap-3 px-5 text-[13px] font-medium transition-opacity hover:opacity-90",
    invert ? "bg-white text-ink" : "bg-ink text-primary-foreground",
  ].join(" ");
}

function secondaryCtaClass(invert: boolean | undefined): string {
  return [
    "inline-flex h-11 items-center gap-3 border px-5 text-[13px] font-medium transition-colors",
    invert
      ? "border-white text-white hover:bg-white hover:text-ink"
      : "border-ink text-ink hover:bg-ink hover:text-primary-foreground",
  ].join(" ");
}

export function NextStepCta({ invert, source }: { invert?: boolean; source: string }) {
  return (
    <section className={shellClass(invert)}>
      <div className="mx-auto flex max-w-[1400px] flex-col gap-8 px-6 py-12 md:flex-row md:items-center md:justify-between md:px-10">
        <div>
          <h2 className="max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]">
            Ready to start?
          </h2>
          <p className={mutedTextClass(invert)}>
            Automatically reduce your AI bill with cost optimization.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <TrackedLink
            href={START_TRIAL_HREF}
            event="trial intent started"
            eventProperties={{ cta: "Start a 14-day trial", source }}
            className={primaryCtaClass(invert)}
          >
            Start a 14-day trial
            <span aria-hidden>→</span>
          </TrackedLink>
          <TrackedLink
            href={ENTERPRISE_FORM_HREF}
            event="sales intent started"
            eventProperties={{ cta: "Talk to sales", source }}
            className={secondaryCtaClass(invert)}
          >
            Talk to sales
            <span aria-hidden>→</span>
          </TrackedLink>
        </div>
      </div>
    </section>
  );
}
