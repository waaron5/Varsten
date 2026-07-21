"use client";

import { useState } from "react";
import Link from "next/link";
import { RequireSession } from "@/components/RequireSession";
import { useEntitlements } from "@/components/entitlements";
import { useSession } from "@/components/session";
import { ApiError, api } from "@/lib/api";
import type { Entitlements } from "@/lib/types";

const CONTACT_HREF = "mailto:contact@varsten.ai?subject=Upgrade%20to%20Varsten%20Optimize";

const OPTIMIZE_INCLUDES = [
  "Turn on savings automations with eval gates and rollback",
  "Smart routing and model-downshift substitution",
  "Response caching and token trimming",
  "Batch routing for non-urgent jobs",
  "Quality guardrails, budget hard caps, and automation",
  "Measured savings attribution and advanced proof",
  "Advanced reports and longer retention",
];

export function UpgradeView() {
  return (
    <RequireSession>
      <UpgradeBody />
    </RequireSession>
  );
}

function UpgradeBody() {
  const { entitlements, isPerformance, observeOnly, observeOnlyReason, planTier, quota, trial, trialProgress } = useEntitlements();
  const billingState = resolveBillingState(entitlements, isPerformance, observeOnly, planTier);
  const paywallActive = observeOnly && ["expired", "past_due", "performance_observe_only"].includes(billingState);
  return (
    <div className="view" style={{ maxWidth: 720 }}>
      {paywallActive ? <OptimizationPaused reason={observeOnlyReason} /> : null}
      <div className="card">
        <div className="card-head">
          <h3>{billingHeading(billingState)}</h3>
          <div className="right">
            <span className={`pill ${billingState === "active" || billingState === "trial_payment_ready" || billingState === "trial_needs_payment" ? "green" : "neutral"}`}>
              {billingPill(billingState, planTier)}
            </span>
          </div>
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <PlanSummary billingState={billingState} trial={trial} />
          <TrialUsageCard observeOnly={observeOnly} paywallActive={paywallActive} quota={quota} trial={trial} />
          <TrialValueChecklist progress={trialProgress} paymentMethodReady={trial?.payment_method_ready === true} />
        </div>
      </div>
    </div>
  );
}

type BillingState =
  | "loading"
  | "trial_needs_payment"
  | "trial_payment_ready"
  | "expired"
  | "active"
  | "past_due"
  | "performance_observe_only"
  | "free";

type BillingRuleContext = {
  entitlements: Entitlements;
  isPerformance: boolean;
  observeOnly: boolean;
};

type BillingRule = (context: BillingRuleContext) => BillingState | null;

const billingRules: BillingRule[] = [
  ({ entitlements }) => (entitlements.subscription_status === "past_due" ? "past_due" : null),
  ({ entitlements }) =>
    entitlements.subscription_status === "expired" || entitlements.trial.trial_expired ? "expired" : null,
  ({ entitlements }) => trialBillingState(entitlements),
  ({ isPerformance, observeOnly }) => (isPerformance && observeOnly ? "performance_observe_only" : null),
  ({ entitlements, isPerformance }) =>
    isPerformance && entitlements.subscription_status === "active" ? "active" : null,
];

function isBillingState(value: BillingState | null): value is BillingState {
  return value !== null;
}

function resolveBillingState(
  entitlements: Entitlements | null,
  isPerformance: boolean,
  observeOnly: boolean,
  planTier: string | null,
): BillingState {
  if (!entitlements || planTier === null) return "loading";
  const context = { entitlements, isPerformance, observeOnly };
  return billingRules.map((rule) => rule(context)).find(isBillingState) ?? "free";
}

function trialBillingState(entitlements: Entitlements): BillingState | null {
  if (entitlements.subscription_status !== "trialing") return null;
  return entitlements.trial.payment_method_ready ? "trial_payment_ready" : "trial_needs_payment";
}

function billingHeading(state: BillingState): string {
  switch (state) {
    case "trial_needs_payment":
      return "Optimize Trial Active";
    case "trial_payment_ready":
      return "Payment Method Ready";
    case "expired":
      return "Trial Ended";
    case "active":
      return "Optimize Active";
    case "past_due":
      return "Resolve Billing";
    case "performance_observe_only":
      return "Optimization Paused";
    case "loading":
      return "Plan";
    default:
      return "Upgrade to Optimize";
  }
}

function billingPill(state: BillingState, planTier: string | null): string {
  if (planTier === null || state === "loading") return "…";
  switch (state) {
    case "trial_needs_payment":
      return "Trial · Payment needed";
    case "trial_payment_ready":
      return "Trial · Ready";
    case "expired":
      return "Expired · Observe-only";
    case "active":
      return "Optimize";
    case "past_due":
      return "Past due";
    case "performance_observe_only":
      return "Observe-only";
    default:
      return "Free · Observe-only";
  }
}

function OptimizationPaused({ reason }: { reason: string | null }) {
  const reasonText = reason === "monthly_request_limit_exceeded"
    ? "the trial request limit has been reached"
    : "the trial window has ended";
  return (
    <div className="card" style={{ borderColor: "var(--warn-line)", background: "var(--warn-faint)", marginBottom: 12 }}>
      <div className="card-head">
        <h3>Optimization paused</h3>
        <div className="right"><span className="pill neutral">Observe-only</span></div>
      </div>
      <div className="es" style={{ padding: "0 12px 12px" }}>
        Your live traffic is still flowing through Varsten, but behavior-changing levers are paused because {reasonText}.
      </div>
    </div>
  );
}

function PlanSummary({
  billingState,
  trial,
}: {
  billingState: BillingState;
  trial: ReturnType<typeof useEntitlements>["trial"];
}) {
  if (billingState === "trial_needs_payment") {
    return (
      <>
        <div className="es">
          Optimize is enabled through the trial. Add a payment method to
          continue after {formatTrialDate(trial?.trial_ends_at)}; setup-mode checkout only
          records payment readiness.
        </div>
        <BillingAction mode="checkout" label="Add payment method to continue after trial" />
        <PricingNote />
      </>
    );
  }
  if (billingState === "trial_payment_ready") {
    return (
      <>
        <div className="es">
          Optimize is enabled and the payment method is ready. When the
          trial ends, Varsten continues on verified-savings pricing without changing your integration.
        </div>
        <BillingAction mode="portal" label="Manage payment method" />
        <PricingNote />
      </>
    );
  }
  if (billingState === "active") {
    return (
      <>
        <div className="es">
          Optimization is enabled for this workspace. Automations, guardrails, and
          measured savings are available across the app.
        </div>
        <BillingAction mode="portal" label="Manage billing" />
        <PricingNote />
      </>
    );
  }
  if (billingState === "past_due") {
    return (
      <>
        <div className="es">
          Traffic still meters and forwards, but behavior-changing levers are paused
          until billing is resolved.
        </div>
        <BillingAction mode="portal" label="Resolve billing" />
      </>
    );
  }
  if (billingState === "expired" || billingState === "performance_observe_only") {
    return (
      <>
        <div className="es">
          The workspace is in observe-only mode. Add a payment method to reactivate
          Optimize and keep the same integration path.
        </div>
        <BillingAction mode="checkout" label="Add payment method and reactivate Optimize" />
        <PricingNote />
      </>
    );
  }
  return (
    <>
      <div className="es">
        Free observes your AI traffic and surfaces estimated savings opportunities. Optimize
        lets Varsten act on them — safely — and proves the savings it captures.
      </div>
      <ul style={{ margin: "12px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>
        {OPTIMIZE_INCLUDES.map((item) => (
          <li key={item} className="es" style={{ listStyle: "disc" }}>{item}</li>
        ))}
      </ul>
      <div className="es" style={{ marginTop: 12, color: "var(--text-2)" }}>
        Activation flips the switch on the integration you already have — the same SDK or base URL,
        no code change. Levers turn on behind eval gates, holdback measurement, and one-click
        rollback, and the fail-open path is unchanged: a Varsten outage still passes straight
        through to your provider.
      </div>
      <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 16 }}>
        <Link className="btn primary" href="/start?intent=trial">Start 14-day Optimize trial</Link>
        <a className="btn" href={CONTACT_HREF}>Talk to us</a>
      </div>
      <PricingNote />
    </>
  );
}

function PricingNote() {
  return (
    <div className="es" style={{ marginTop: 10 }}>
      Optimize uses verified-savings pricing: if Varsten saves nothing, you pay nothing.
    </div>
  );
}

function formatTrialDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString() : "the trial end date";
}

function useActiveOrgId(): string | null {
  const { projects, activeProjectId } = useSession();
  const project = projects.find((p) => p.id === activeProjectId) ?? projects[0];
  return project?.organization_id ?? null;
}

async function billingSessionUrl(mode: "checkout" | "portal", token: string, orgId: string): Promise<string> {
  const { url } = mode === "portal"
    ? await api.billingPortalSession(token, orgId)
    : await api.billingCheckoutSession(token, orgId);
  return url;
}

function billingErrorMessage(error: unknown, mode: "checkout" | "portal"): string {
  if (error instanceof ApiError && error.status === 503) {
    return "Self-serve billing is not available in this environment. Contact Varsten to set up verified-savings pricing.";
  }
  if (error instanceof ApiError && error.status === 409 && mode === "portal") {
    return "Add a payment method before opening the billing portal.";
  }
  return error instanceof Error ? error.message : String(error);
}

function BillingAction({
  mode,
  label,
}: {
  mode: "checkout" | "portal";
  label: string;
}) {
  const { getToken } = useSession();
  const orgId = useActiveOrgId();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const startBillingFlow = async () => {
    if (!orgId) return;
    setBusy(true);
    setErr(null);
    try {
      const token = await getToken();
      window.location.href = await billingSessionUrl(mode, token, orgId);
    } catch (e) {
      setErr(billingErrorMessage(e, mode));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 16 }}>
        <button className="btn primary" disabled={busy || !orgId} onClick={() => void startBillingFlow()}>
          {busy ? "Opening…" : label}
        </button>
        <a className="btn" href={CONTACT_HREF}>Talk to us</a>
      </div>
      {err && <div className="es" style={{ color: "var(--neg)", marginTop: 8 }}>{err}</div>}
    </>
  );
}

function TrialUsageCard({
  observeOnly,
  paywallActive,
  quota,
  trial,
}: {
  observeOnly: boolean;
  paywallActive: boolean;
  quota: ReturnType<typeof useEntitlements>["quota"];
  trial: ReturnType<typeof useEntitlements>["trial"];
}) {
  const quotaUsed = quota ? `${quota.monthly_requests.toLocaleString()} / ${quota.monthly_request_limit.toLocaleString()}` : "—";
  const trialEnds = trial?.trial_ends_at ? new Date(trial.trial_ends_at).toLocaleDateString() : "—";
  return (
    <div style={{ margin: "18px 0 0" }}>
      <div className="card-head">
        <h3>Trial usage</h3>
        <div className="right">
          <span className={`pill ${paywallActive ? "neutral" : "green"}`}>
            {paywallActive ? "Paused" : "Available"}
          </span>
        </div>
      </div>
      <table className="tbl">
        <tbody>
          <tr><td className="muted">Monthly observed requests</td><td>{quotaUsed}</td></tr>
          <tr><td className="muted">Requests remaining</td><td>{quota?.requests_remaining?.toLocaleString() ?? "—"}</td></tr>
          <tr><td className="muted">Trial ends</td><td>{trialEnds}</td></tr>
          <tr><td className="muted">Mode</td><td>{observeOnly ? "Observe-only" : "Optimize"}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function TrialValueChecklist({
  progress,
  paymentMethodReady,
}: {
  progress: ReturnType<typeof useEntitlements>["trialProgress"];
  paymentMethodReady: boolean;
}) {
  if (!progress) return null;
  const holdbackDetail = progress.holdback_policy_active
    ? `${progress.holdback_control_count} / ${progress.holdback_arm_threshold} control, ${progress.holdback_treatment_count} / ${progress.holdback_arm_threshold} treatment`
    : "Available after a holdback-measured lever is active";
  const items = [
    {
      label: "First request received",
      complete: progress.first_request_received,
      detail: progress.first_request_received ? "Traffic is visible." : "Send one request through the selected onboarding path.",
      href: "/onboarding",
      action: "Open onboarding",
    },
    {
      label: "At least one priced request",
      complete: progress.priced_request_count > 0,
      detail: `${progress.priced_request_count} priced requests seen.`,
      href: "/dashboard",
      action: "Review traffic",
    },
    {
      label: "Directional spend patterns",
      complete: progress.directional_spend_ready,
      detail: `${progress.priced_request_count} / ${progress.directional_request_threshold} priced requests.`,
      href: "/dashboard",
      action: "Send more traffic",
    },
    {
      label: "Holdback proof volume",
      complete: progress.holdback_proof_ready,
      detail: holdbackDetail,
      href: "/automation",
      action: progress.holdback_policy_active ? "Watch proof" : "Turn on automation",
    },
    {
      label: "Payment method ready",
      complete: paymentMethodReady,
      detail: paymentMethodReady ? "Ready to continue after trial." : "Add payment method before trial end.",
      href: "/upgrade",
      action: "Manage plan",
    },
  ];
  return (
    <div style={{ marginTop: 20 }}>
      <div className="card-head" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <h3>Trial value checklist</h3>
        <div className="right"><span className="pill neutral">Deterministic</span></div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {items.map((item) => (
          <div
            key={item.label}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto",
              gap: 12,
              alignItems: "center",
              padding: "10px 0",
              borderTop: "1px solid var(--line)",
            }}
          >
            <div>
              <div style={{ fontWeight: 650 }}>{item.complete ? "Done: " : ""}{item.label}</div>
              <div className="es">{item.detail}</div>
            </div>
            <Link className="btn small" href={item.href}>{item.action}</Link>
          </div>
        ))}
      </div>
    </div>
  );
}
