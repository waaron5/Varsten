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
      <Link href="/upgrade" className="btn primary">Upgrade to Pro</Link>
    </div>
  );
}
