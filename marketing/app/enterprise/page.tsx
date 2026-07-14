import type { Metadata } from "next";
import { LeadForm } from "@/components/varsten/LeadForm";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Enterprise — Varsten",
  description:
    "Enterprise AI cost optimization rollout planning for governance, security review, support posture, and pilot expectations.",
  path: "/enterprise",
});

export default function EnterprisePage() {
  return (
    <SecondaryShell>
      <section className="min-h-[calc(100svh-3.5rem)] border-b border-border bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            Enterprise
          </h1>
          <div className="mt-10 grid min-w-0 md:mt-12">
            <LeadForm source="enterprise" mode="enterprise" submitLabel="Book a call" />
          </div>
        </div>
      </section>
    </SecondaryShell>
  );
}
