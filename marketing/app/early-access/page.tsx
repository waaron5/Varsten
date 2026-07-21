import type { Metadata } from "next";
import { LeadForm } from "@/components/varsten/LeadForm";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Request early access — Varsten",
  description: "Request founder-led early access to Varsten Optimize during the public preview.",
  path: "/early-access",
});

export default function EarlyAccessPage() {
  return (
    <SecondaryShell>
      <section className="min-h-[calc(100svh-3.5rem)] border-b border-border bg-background">
        <div className="mx-auto grid w-full max-w-[1400px] gap-10 px-6 py-16 md:px-10 md:py-20 lg:grid-cols-[minmax(0,0.8fr)_minmax(520px,1.2fr)] lg:gap-16">
          <div>
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-blueprint">Public preview</p>
            <h1 className="mt-5 text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
              Request early access
            </h1>
            <p className="mt-7 max-w-xl text-[16px] leading-7 text-ink-soft">
              Varsten is onboarding Optimize users selectively while the public preview is underway. Tell us who
              you are and what you want to improve; submitting this form requests access rather than activating
              production optimization automatically.
            </p>
            <div className="mono mt-8 border-t border-border pt-5 text-[11px] uppercase tracking-[0.18em] text-ink-soft">
              Founder reviewed · No credit card · No provider key required
            </div>
          </div>
          <div>
            <LeadForm source="early-access" mode="early-access" submitLabel="Request early access" />
          </div>
        </div>
      </section>
    </SecondaryShell>
  );
}
