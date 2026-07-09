"use client";

import { useState } from "react";
import { getMarketingAnonymousId, trackMarketingEvent } from "./analytics/AnalyticsProvider";

type LeadFormProps = {
  source: string;
  submitLabel?: string;
};

type FormState = "idle" | "submitting" | "success" | "error";

export function LeadForm({ source, submitLabel = "Request a setup call" }: LeadFormProps) {
  const [state, setState] = useState<FormState>("idle");
  const [started, setStarted] = useState(false);

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

    const formData = new FormData(event.currentTarget);
    const params = new URLSearchParams(window.location.search);

    const payload = {
      email: String(formData.get("email") || ""),
      fullName: String(formData.get("fullName") || ""),
      companyName: String(formData.get("companyName") || ""),
      source,
      anonymousId: getMarketingAnonymousId(),
      pagePath: window.location.pathname,
      utmSource: params.get("utm_source") || "",
      utmMedium: params.get("utm_medium") || "",
      utmCampaign: params.get("utm_campaign") || "",
    };

    try {
      const response = await fetch("/api/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        trackMarketingEvent("lead form failed", { source, status: response.status });
        setState("error");
        return;
      }

      setState("success");
      event.currentTarget.reset();
    } catch {
      trackMarketingEvent("lead form failed", { source, status: "network" });
      setState("error");
    }
  }

  return (
    <form
      onFocus={markStarted}
      onSubmit={onSubmit}
      className="grid gap-3 border border-border bg-background p-4 md:grid-cols-2"
    >
      <label className="grid gap-1 text-[13px] font-medium text-ink">
        Name
        <input
          required
          name="fullName"
          autoComplete="name"
          className="h-11 border border-border bg-background px-3 text-[14px] outline-none transition-colors focus:border-ink"
        />
      </label>
      <label className="grid gap-1 text-[13px] font-medium text-ink">
        Work email
        <input
          required
          name="email"
          type="email"
          autoComplete="email"
          className="h-11 border border-border bg-background px-3 text-[14px] outline-none transition-colors focus:border-ink"
        />
      </label>
      <label className="grid gap-1 text-[13px] font-medium text-ink md:col-span-2">
        Company
        <input
          required
          name="companyName"
          autoComplete="organization"
          className="h-11 border border-border bg-background px-3 text-[14px] outline-none transition-colors focus:border-ink"
        />
      </label>
      <div className="flex flex-col gap-3 pt-2 md:col-span-2 md:flex-row md:items-center">
        <button
          type="submit"
          disabled={state === "submitting" || state === "success"}
          className="inline-flex h-11 items-center justify-center bg-ink px-4 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {state === "submitting" ? "Sending..." : state === "success" ? "Request sent" : submitLabel}
        </button>
        <p className="text-[12px] leading-5 text-ink-soft">
          {state === "success"
            ? "We received it and will follow up with setup next steps."
            : state === "error"
              ? "Something failed. Email mail@varsten.ai if this keeps happening."
              : "No prompt text, provider keys, or message content belongs in this form."}
        </p>
      </div>
    </form>
  );
}
