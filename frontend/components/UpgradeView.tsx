"use client";

import { RequireSession } from "@/components/RequireSession";
import { useEntitlements } from "@/components/entitlements";

const CONTACT_HREF = "mailto:mail@varsten.ai?subject=Upgrade%20to%20Varsten%20Performance";

const PERFORMANCE_INCLUDES = [
  "Apply recommendations one-click, with eval gates and rollback",
  "Smart routing and cheaper-model substitution",
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
  const { isPerformance, planTier } = useEntitlements();

  return (
    <div className="view" style={{ maxWidth: 720 }}>
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
          {isPerformance ? (
            <div className="es">
              Optimization is enabled for this workspace. You can apply recommendations and capture
              verified savings across the Engine.
            </div>
          ) : (
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
          )}
        </div>
      </div>
    </div>
  );
}
