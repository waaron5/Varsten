import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { NextStepCta } from "@/components/varsten/NextStepCta";
import { FaqAccordion } from "@/components/varsten/faq/FaqAccordion";

export const metadata: Metadata = pageMetadata({
  title: "FAQ — Varsten",
  description:
    "Answers to common Varsten questions about AI cost optimization, provider support, integration paths, data handling, and verified savings.",
  path: "/faq",
});

export default function FaqPage() {
  return (
    <SecondaryShell>
      <section className="flex min-h-[calc(100svh-3.5rem)] flex-col justify-between border-b border-border bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            FAQ
          </h1>
        </div>
        <div className="mx-auto w-full max-w-[1400px] px-6 pb-12 md:px-10 md:pb-16">
          <FaqAccordion />
        </div>
      </section>

      <NextStepCta invert source="faq_next_step" />
    </SecondaryShell>
  );
}
