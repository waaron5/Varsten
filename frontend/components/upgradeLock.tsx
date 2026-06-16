"use client";

// Shared, calm paywall UI. One contextual CTA per locked section, and an
// effective-status badge that never shows a misleading "active" to Free users.
// All plan logic comes from useEntitlements — never re-derived per component.

import type { ReactNode } from "react";
import Link from "next/link";

export function LockedNotice({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="locked-notice">
      <div className="locked-notice-text">
        <strong>{title}</strong>
        {children ? <span>{children}</span> : null}
      </div>
      <Link href="/upgrade" className="btn primary">Upgrade to Performance</Link>
    </div>
  );
}

// Effective status, not raw config: for observe-only (Free), a lever/route/trim is
// never "active" regardless of its stored enabled flag.
export function EffectiveStatusBadge({
  observeOnly,
  active,
  lockedLabel = "Available on Performance",
}: {
  observeOnly: boolean;
  active: boolean;
  lockedLabel?: string;
}) {
  if (observeOnly) return <span className="pill neutral">{lockedLabel}</span>;
  return <span className={`pill ${active ? "green" : "neutral"}`}>{active ? "active" : "paused"}</span>;
}
