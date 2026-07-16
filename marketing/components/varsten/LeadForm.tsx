"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { CONTACT_EMAIL } from "@/app/site-links";
import { getMarketingAnonymousId, trackMarketingEvent } from "./analytics/AnalyticsProvider";

type LeadFormProps = {
  source: string;
  mode?: "basic" | "enterprise";
  submitLabel?: string;
};

type FormState = "idle" | "submitting" | "success" | "error";
type LeadResponse = {
  ok?: boolean;
  buyerEmailSent?: boolean;
};
type LeadSubmitResult =
  | { ok: true; body: LeadResponse }
  | { ok: false; status: number | "network" };

const inputClass =
  "h-11 border border-border bg-background px-3 text-[14px] outline-none transition-colors focus:border-ink";
const labelClass = "grid gap-1 text-[13px] font-medium text-ink";
const enterpriseInputClass =
  "h-11 border border-border bg-white px-3 text-[14px] text-ink outline-none transition-colors focus:border-ink";
const enterpriseLabelClass = "mono grid gap-2 text-[11px] uppercase tracking-[0.18em] text-ink-soft";

function formValue(formData: FormData, key: string): string {
  return String(formData.get(key) || "");
}

function leadPayloadFromForm(form: HTMLFormElement, source: string) {
  const formData = new FormData(form);
  const params = new URLSearchParams(window.location.search);
  return {
    email: formValue(formData, "email"),
    fullName: formValue(formData, "fullName"),
    companyName: formValue(formData, "companyName"),
    monthlySpendRange: formValue(formData, "monthlySpendRange"),
    primaryProviders: formValue(formData, "primaryProviders"),
    primaryProvidersOther: formValue(formData, "primaryProvidersOther"),
    mainGoal: formValue(formData, "mainGoal"),
    note: formValue(formData, "note"),
    source,
    anonymousId: getMarketingAnonymousId(),
    pagePath: window.location.pathname,
    utmSource: params.get("utm_source") || "",
    utmMedium: params.get("utm_medium") || "",
    utmCampaign: params.get("utm_campaign") || "",
  };
}

async function submitLead(payload: ReturnType<typeof leadPayloadFromForm>): Promise<LeadSubmitResult> {
  try {
    const response = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) return { ok: false, status: response.status };
    return { ok: true, body: (await response.json()) as LeadResponse };
  } catch {
    return { ok: false, status: "network" };
  }
}

function trackLeadFailure(source: string, status: number | "network") {
  trackMarketingEvent("lead form failed", { source, status });
}

function useLeadFormController(source: string) {
  const [state, setState] = useState<FormState>("idle");
  const [started, setStarted] = useState(false);
  const [buyerEmailSent, setBuyerEmailSent] = useState(false);
  const [primaryProviders, setPrimaryProviders] = useState("");

  function markStarted() {
    if (started) return;
    setStarted(true);
    trackMarketingEvent("lead form started", { source });
    trackMarketingEvent("sales intent started", { source });
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    markStarted();
    setState("submitting");

    const form = event.currentTarget;
    const result = await submitLead(leadPayloadFromForm(form, source));
    if (!result.ok) {
      trackLeadFailure(source, result.status);
      setState("error");
      return;
    }

    setBuyerEmailSent(Boolean(result.body.buyerEmailSent));
    setState("success");
    setPrimaryProviders("");
    form.reset();
  }

  return {
    buyerEmailSent,
    markStarted,
    onSubmit,
    primaryProviders,
    setPrimaryProviders,
    state,
  };
}

export function LeadForm({ source, mode = "basic", submitLabel = "Request a setup call" }: LeadFormProps) {
  return (
    <LeadFormView
      form={useLeadFormController(source)}
      isEnterprise={mode === "enterprise"}
      source={source}
      submitLabel={submitLabel}
    />
  );
}

type LeadFormController = ReturnType<typeof useLeadFormController>;
type LeadFormViewProps = {
  form: LeadFormController;
  isEnterprise: boolean;
  source: string;
  submitLabel: string;
};

const leadFormViews: Record<FormState, (props: LeadFormViewProps) => ReactNode> = {
  idle: LeadFormShell,
  submitting: LeadFormShell,
  error: LeadFormShell,
  success: LeadFormSuccessState,
};

function LeadFormView(props: LeadFormViewProps) {
  const View = leadFormViews[props.form.state];
  return <View {...props} />;
}

function LeadFormShell({ form, isEnterprise, submitLabel }: LeadFormViewProps) {
  return (
    <form
      onFocus={form.markStarted}
      onSubmit={form.onSubmit}
      className={leadFormClass(isEnterprise)}
    >
      <div className={isEnterprise ? "grid gap-4 border border-border bg-background p-4 md:grid-cols-2 md:p-6" : "contents"}>
        <BaseLeadFields isEnterprise={isEnterprise} />
        {isEnterprise ? (
          <EnterpriseFields primaryProviders={form.primaryProviders} onPrimaryProvidersChange={form.setPrimaryProviders} />
        ) : null}
        <LeadFormActions isEnterprise={isEnterprise} state={form.state} submitLabel={submitLabel} />
      </div>
      {isEnterprise ? <EnterpriseAside /> : null}
    </form>
  );
}

function LeadFormSuccessState({ form, isEnterprise, source }: LeadFormViewProps) {
  return <LeadFormSuccess buyerEmailSent={form.buyerEmailSent} isEnterprise={isEnterprise} source={source} />;
}

function leadFormClass(isEnterprise: boolean): string {
  return isEnterprise
    ? "grid gap-4 md:gap-6 lg:grid-cols-[minmax(0,1fr)_360px]"
    : "grid gap-4 border border-border bg-background p-4 md:grid-cols-2 md:p-6";
}

function LeadFormSuccess({
  buyerEmailSent,
  isEnterprise,
  source,
}: {
  buyerEmailSent: boolean;
  isEnterprise: boolean;
  source: string;
}) {
  return (
    <div className={successShellClass(isEnterprise)} role="status">
      <p className="mono text-[10px] uppercase tracking-[0.28em] text-blueprint">Request received</p>
      <h2 className={successTitleClass(isEnterprise)}>
        We have what we need.
      </h2>
      <p className={successBodyClass(isEnterprise)}>
        {successMessage(buyerEmailSent)}
      </p>
      <SuccessActions isEnterprise={isEnterprise} source={source} />
    </div>
  );
}

function successShellClass(isEnterprise: boolean): string {
  return ["border p-6", isEnterprise ? "border-ink bg-ink text-white" : "border-border bg-background"].join(" ");
}

function successTitleClass(isEnterprise: boolean): string {
  return ["mt-4 text-[26px] font-semibold tracking-[-0.01em]", isEnterprise ? "text-white" : "text-ink"].join(" ");
}

function successBodyClass(isEnterprise: boolean): string {
  return ["mt-3 max-w-2xl text-[14px] leading-6", isEnterprise ? "text-white/70" : "text-ink-soft"].join(" ");
}

function successMessage(buyerEmailSent: boolean): string {
  return buyerEmailSent
    ? "A confirmation is on its way to your work email. We will review your provider mix, spend range, and rollout goal before following up."
    : "We received your request. We will review your provider mix, spend range, and rollout goal before following up.";
}

function SuccessActions({ isEnterprise, source }: { isEnterprise: boolean; source: string }) {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <Link
        href="/security"
        onClick={() => trackMarketingEvent("cta clicked", { source, cta: "Review security", href: "/security" })}
        className={[
          "inline-flex h-11 items-center gap-3 px-5 text-[13px] font-medium transition-opacity hover:opacity-90",
          isEnterprise ? "bg-white text-ink" : "bg-ink text-primary-foreground",
        ].join(" ")}
      >
        Review security
        <span aria-hidden>→</span>
      </Link>
      <Link
        href="/docs/quickstart"
        onClick={() => trackMarketingEvent("cta clicked", { source, cta: "Read docs", href: "/docs/quickstart" })}
        className={[
          "inline-flex h-11 items-center gap-3 border px-5 text-[13px] font-medium transition-colors",
          isEnterprise
            ? "border-white text-white hover:bg-white hover:text-ink"
            : "border-ink text-ink hover:bg-ink hover:text-primary-foreground",
        ].join(" ")}
      >
        Read docs
        <span aria-hidden>→</span>
      </Link>
    </div>
  );
}

function BaseLeadFields({ isEnterprise }: { isEnterprise: boolean }) {
  const fieldClass = isEnterprise ? enterpriseLabelClass : labelClass;
  const input = isEnterprise ? enterpriseInputClass : inputClass;
  return (
    <>
      <label className={fieldClass}>
        Name
        <input required name="fullName" autoComplete="name" className={input} />
      </label>
      <label className={fieldClass}>
        Work email
        <input required name="email" type="email" autoComplete="email" className={input} />
      </label>
      <label className={fieldClass}>
        Company
        <input required name="companyName" autoComplete="organization" className={input} />
      </label>
    </>
  );
}

function EnterpriseFields({
  onPrimaryProvidersChange,
  primaryProviders,
}: {
  onPrimaryProvidersChange: (value: string) => void;
  primaryProviders: string;
}) {
  return (
    <>
      <label className={enterpriseLabelClass}>
        Monthly AI/API spend range
        <select required name="monthlySpendRange" className={enterpriseInputClass} defaultValue="">
          <option value="" disabled>Select range</option>
          <option>Under $10k/mo</option>
          <option>$10k-$50k/mo</option>
          <option>$50k-$250k/mo</option>
          <option>$250k+/mo</option>
          <option>Not sure</option>
        </select>
      </label>
      <PrimaryProvidersField value={primaryProviders} onChange={onPrimaryProvidersChange} />
      {primaryProviders === "Other" ? (
        <label className={enterpriseLabelClass}>
          Enter providers
          <input required name="primaryProvidersOther" className={enterpriseInputClass} />
        </label>
      ) : null}
      <label className={enterpriseLabelClass}>
        Main goal
        <select required name="mainGoal" className={enterpriseInputClass} defaultValue="">
          <option value="" disabled>Select goal</option>
          <option>AI cost reduction</option>
          <option>AI spend visibility</option>
          <option>Both</option>
        </select>
      </label>
      <label className={`${enterpriseLabelClass} md:col-span-2`}>
        Optional note
        <textarea
          name="note"
          rows={4}
          className="min-h-28 resize-y border border-border bg-white px-3 py-3 text-[14px] text-ink outline-none transition-colors focus:border-ink"
        />
      </label>
    </>
  );
}

function PrimaryProvidersField({ onChange, value }: { onChange: (value: string) => void; value: string }) {
  return (
    <label className={enterpriseLabelClass}>
      Primary providers
      <select
        required
        name="primaryProviders"
        className={enterpriseInputClass}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" disabled>Select provider mix</option>
        <option>OpenAI</option>
        <option>Anthropic</option>
        <option>Google Gemini</option>
        <option>Mixed / multiple</option>
        <option>Other</option>
      </select>
    </label>
  );
}

function LeadFormActions({
  isEnterprise,
  state,
  submitLabel,
}: {
  isEnterprise: boolean;
  state: FormState;
  submitLabel: string;
}) {
  return (
    <div className={["flex flex-col gap-3 pt-2 md:col-span-2", isEnterprise ? "md:flex-row md:items-center md:justify-between" : "items-start"].join(" ")}>
      <div className="flex flex-col items-start gap-3">
        <button
          type="submit"
          disabled={state === "submitting"}
          className="inline-flex h-11 w-fit items-center justify-center bg-ink px-4 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {state === "submitting" ? "Sending..." : submitLabel}
        </button>
        <LeadFormHelperText isEnterprise={isEnterprise} state={state} />
      </div>
      {isEnterprise ? <EmailFallback /> : null}
    </div>
  );
}

function LeadFormHelperText({ isEnterprise, state }: { isEnterprise: boolean; state: FormState }) {
  if (state === "error") {
    return <p className="text-[12px] leading-5 text-ink-soft">Something failed. Email mail@varsten.ai if this keeps happening.</p>;
  }
  if (isEnterprise) return null;
  return <p className="text-[12px] leading-5 text-ink-soft">No prompt text, provider keys, or message content belongs in this form.</p>;
}

function EmailFallback() {
  return (
    <p className="text-[13px] leading-6 text-ink-soft md:text-right">
      Prefer email?{" "}
      <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>
        {CONTACT_EMAIL}
      </a>
    </p>
  );
}

function EnterpriseAside() {
  return (
    <aside className="border border-ink bg-ink p-4 md:p-6">
      <div className="mono grid gap-6 text-[11px] uppercase tracking-[0.18em] text-white/70">
        <EnterpriseAsideSection title="What happens next">
          We review your spend range, provider mix, and rollout goal before suggesting a first pilot path.
        </EnterpriseAsideSection>
        <section>
          <div className="text-white">Useful context</div>
          <ul className="mt-3 grid gap-2 text-[12px] leading-5 normal-case tracking-normal text-white/65">
            <li>Provider routing or gateway already in place</li>
            <li>Security review timing</li>
            <li>One workload that is safe to pilot first</li>
          </ul>
        </section>
        <EnterpriseAsideSection title="Not needed here">
          No prompt text, API keys, customer data, or message content belongs in this form.
        </EnterpriseAsideSection>
      </div>
    </aside>
  );
}

function EnterpriseAsideSection({ children, title }: { children: string; title: string }) {
  return (
    <section>
      <div className="text-white">{title}</div>
      <p className="mt-3 text-[12px] leading-6 normal-case tracking-normal text-white/65">{children}</p>
    </section>
  );
}
