"use client";

import { RequireSession } from "@/components/RequireSession";
import { useEntitlements } from "@/components/entitlements";

const CONTACT_HREF = "mailto:mail@varsten.ai?subject=Upgrade%20to%20Varsten%20Performance";

const PERFORMANCE_INCLUDES = [
  "Apply recommendations one-click, with eval gates and rollback",
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
  const { isPerformance, observeOnly, observeOnlyReason, planTier, quota, trial } = useEntitlements();
  const paywallActive = observeOnly && planTier === "performance";
  return (
    <div className="view" style={{ maxWidth: 720 }}>
      {paywallActive ? <OptimizationPaused reason={observeOnlyReason} /> : null}
      <div className="card">
        <div className="card-head">
          <h3>{isPerformance ? "You're on Performance" : "Upgrade to Performance"}</h3>
          <div className="right">
            <span className={`pill ${isPerformance ? "green" : "neutral"}`}>
              {planTier === null ? "…" : isPerformance ? "Performance" : "Free · Observe-only"}
            </span>
          </div>
        </div>
        <div style={{ padding: "0 12px 12px" }}>
          <PlanSummary isPerformance={isPerformance} />
          <TrialUsageCard observeOnly={observeOnly} paywallActive={paywallActive} quota={quota} trial={trial} />
        </div>
      </div>
    </div>
  );
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

function PlanSummary({ isPerformance }: { isPerformance: boolean }) {
  if (isPerformance) {
    return (
      <div className="es">
        Optimization is enabled for this workspace. You can apply recommendations and capture
        verified savings across the Engine.
      </div>
    );
  }
  return (
    <>
      <div className="es">
        Free observes your AI traffic and surfaces estimated savings opportunities. Performance
        lets Varsten act on them — safely — and proves the savings it captures.
      </div>
      <ul style={{ margin: "12px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>
        {PERFORMANCE_INCLUDES.map((item) => (
          <li key={item} className="es" style={{ listStyle: "disc" }}>{item}</li>
        ))}
      </ul>
      <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 16 }}>
        <a className="btn primary" href={CONTACT_HREF}>Talk to us about Performance</a>
      </div>
      <div className="es" style={{ marginTop: 10 }}>
        Varsten Performance is billed as a percentage of verified savings — if Varsten saves
        nothing, you pay nothing.
      </div>
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
    <div className="card" style={{ boxShadow: "none", margin: "16px 0 0" }}>
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
          <tr><td className="muted">Mode</td><td>{observeOnly ? "Observe-only" : "Performance optimization"}</td></tr>
        </tbody>
      </table>
    </div>
  );
}
