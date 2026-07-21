import type { Metadata } from "next";
import { CONTACT_EMAIL, DPA_REQUEST_HREF } from "../site-links";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { FullShowcaseSection, SplitShowcaseSection } from "@/components/varsten/ShowcaseSection";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Security — Varsten",
  description: "Varsten security architecture, credential handling, data boundaries, reliability controls, and current compliance posture.",
  path: "/security",
});

const controls = [
  ["Tenant boundaries", "Project-scoped credentials and organization ownership checks isolate customer resources across the control plane."],
  ["Least privilege", "Application roles and infrastructure permissions are scoped to the resources required for their runtime responsibilities."],
  ["Auditability", "Security-sensitive account, credential, and administrative actions are designed to produce attributable audit records."],
  ["Encrypted transport", "Public application and API traffic uses TLS. Sensitive configuration is kept out of client-side code and analytics."],
] as const;

const dataPaths = [
  {
    title: "Metadata-only",
    posture: "No inline content path",
    description: "Send provider, model, token, cost, and workload labels after your own provider call. Prompts and responses stay out of Varsten.",
  },
  {
    title: "Production SDK",
    posture: "Provider key stays local",
    description: "The Varsten key authenticates the optimized path. Your provider key remains in the application for direct fallback.",
  },
  {
    title: "Base URL evaluation",
    posture: "Connected provider credential",
    description: "Varsten processes content in transit and uses a connected provider credential. This path should be reviewed before sensitive use.",
  },
] as const;

export default function SecurityPage() {
  return (
    <SecondaryShell>
      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">Security</h1>
          <p className="mt-7 max-w-3xl text-[17px] leading-8 text-ink-soft">Choose the data path that matches the workload, keep credentials bounded, and preserve a direct fallback for production traffic.</p>
        </div>
      </section>

      <SplitShowcaseSection eyebrow="01 · Data paths" title="Security starts with how you connect.">
          <div className="grid gap-px border border-border bg-border lg:grid-cols-3">
            {dataPaths.map((path) => (
              <article key={path.title} className="flex min-h-[310px] flex-col bg-white p-7">
                <p className="mono text-[9px] uppercase tracking-[0.2em] text-ink-soft">{path.posture}</p>
                <h3 className="mt-auto pt-16 text-[22px] font-semibold text-ink">{path.title}</h3>
                <p className="mt-3 text-[13px] leading-6 text-ink-soft">{path.description}</p>
              </article>
            ))}
          </div>
      </SplitShowcaseSection>

      <FullShowcaseSection eyebrow="02 · Controls" title="Current operating controls.">
          <div className="mt-14 grid gap-px border border-border bg-border md:grid-cols-2">
            {controls.map(([title, description]) => (
              <article key={title} className="min-h-[220px] bg-white p-7 md:p-9">
                <span className="inline-flex h-5 w-5 items-center justify-center bg-ink text-[10px] text-white" aria-hidden="true">✓</span>
                <h3 className="mt-10 text-[20px] font-semibold text-ink">{title}</h3>
                <p className="mt-3 max-w-lg text-[14px] leading-6 text-ink-soft">{description}</p>
              </article>
            ))}
          </div>
      </FullShowcaseSection>

      <SplitShowcaseSection eyebrow="03 · Reliability" title="An outage should not become your outage.">
          <div className="border-y border-border">
            {[
              ["Direct provider fallback", "SDK wrappers can bypass Varsten for eligible transport or Varsten-origin failures before output starts."],
              ["No unsafe replay", "Provider-origin errors, deliberate budget caps, and mid-stream failures are surfaced rather than retried blindly."],
              ["Circuit breaking", "Repeated Varsten failures open a local breaker so applications do not pay the same failed timeout on every call."],
            ].map(([title, description], index) => (
              <article key={title} className="grid gap-4 border-b border-border py-7 last:border-b-0 sm:grid-cols-[64px_0.55fr_1fr] sm:gap-7">
                <span className="mono text-[10px] tracking-[0.22em] text-ink-soft">{String(index + 1).padStart(2, "0")}</span>
                <h3 className="text-[17px] font-semibold text-ink">{title}</h3>
                <p className="text-[14px] leading-6 text-ink-soft">{description}</p>
              </article>
            ))}
          </div>
      </SplitShowcaseSection>

      <section className="border-b border-border bg-ink text-white">
        <div className="mx-auto grid max-w-[1400px] gap-10 px-6 py-16 md:px-10 md:py-20 lg:grid-cols-2">
          <div>
            <p className="mono text-[10px] uppercase tracking-[0.24em] text-white/50">Current posture</p>
            <h2 className="mt-4 text-[30px] font-semibold tracking-[-0.02em] md:text-[42px]">Not yet SOC 2 certified.</h2>
            <p className="mt-4 max-w-xl text-[14px] leading-7 text-white/65">Varsten is building toward formal assurance but does not claim a SOC 2 report, penetration-test certification, or compliance status that does not exist.</p>
          </div>
          <div className="border-t border-white/20 pt-6 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
            <p className="text-[14px] leading-7 text-white/70">For questionnaires, vulnerability reports, architecture review, or available security materials, email <a className="text-white underline underline-offset-4" href="mailto:security@varsten.ai">security@varsten.ai</a>.</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <a href={DPA_REQUEST_HREF} className="inline-flex h-11 items-center gap-3 bg-white px-5 text-[13px] font-medium text-ink">Request a DPA <span aria-hidden="true">→</span></a>
              <a href={`mailto:${CONTACT_EMAIL}?subject=Security%20review`} className="inline-flex h-11 items-center gap-3 border border-white px-5 text-[13px] font-medium text-white">Start a security review <span aria-hidden="true">→</span></a>
            </div>
          </div>
        </div>
      </section>

    </SecondaryShell>
  );
}
