import type { Metadata } from "next";
import { CONTACT_EMAIL } from "../site-links";
import { LeadForm } from "@/components/varsten/LeadForm";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Contact — Varsten",
  description: "Contact Varsten about product evaluation, support, security, partnerships, or procurement.",
  path: "/contact",
});

const contactRoutes = [
  ["General and sales", CONTACT_EMAIL, "Product evaluation, partnerships, procurement, and general questions."],
  ["Support", "support@varsten.ai", "Account, integration, and product-support questions."],
  ["Security", "security@varsten.ai", "Vulnerability reports, questionnaires, and security review."],
] as const;

export default function ContactPage() {
  return (
    <SecondaryShell>
      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">Contact</h1>
          <p className="mt-7 max-w-2xl text-[17px] leading-8 text-ink-soft">Tell us what you are evaluating or where you are blocked. Your message will be routed to the right place.</p>
        </div>
      </section>

      <section className="border-b border-border bg-background">
        <div className="mx-auto grid max-w-[1400px] gap-14 px-6 py-20 md:px-10 md:py-28 lg:grid-cols-[minmax(220px,0.38fr)_minmax(0,1fr)] lg:gap-20">
          <div>
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">Send a message</p>
            <h2 className="mt-4 max-w-sm text-[28px] font-semibold leading-[1.15] tracking-[-0.02em] text-ink md:text-[38px]">A little context is enough.</h2>
            <p className="mt-5 max-w-sm text-[14px] leading-7 text-ink-soft">Do not include API keys, prompts, completions, customer content, or other secrets.</p>
          </div>
          <LeadForm source="contact" mode="contact" submitLabel="Send message" />
        </div>
      </section>

      <section className="border-b border-border bg-muted">
        <div className="mx-auto max-w-[1400px] px-6 py-20 md:px-10 md:py-28">
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">Direct contacts</p>
          <div className="mt-10 grid gap-px border border-border bg-border md:grid-cols-3">
            {contactRoutes.map(([title, email, description]) => (
              <article key={title} className="min-h-[220px] bg-white p-7">
                <h2 className="text-[18px] font-semibold text-ink">{title}</h2>
                <p className="mt-3 text-[13px] leading-6 text-ink-soft">{description}</p>
                <a className="mt-10 inline-flex items-center gap-3 text-[13px] font-medium text-ink underline decoration-border-strong underline-offset-4" href={`mailto:${email}`}>{email}<span aria-hidden="true">→</span></a>
              </article>
            ))}
          </div>
        </div>
      </section>
    </SecondaryShell>
  );
}
