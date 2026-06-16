"use client";

// Top-of-dashboard setup checklist, shown only until the first request arrives so
// a fresh workspace never looks broken. Observe-only status itself lives in the
// persistent nav plan badge, not a banner. Derives from onboarding status.

import Link from "next/link";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import type { OnboardingStatus } from "@/lib/types";

const SETUP_CALL_HREF = "mailto:mail@varsten.ai?subject=Varsten%20setup%20call";

function Tick({ done }: { done: boolean }) {
  return <span className={`pill ${done ? "green" : "neutral"}`} style={{ marginRight: 8 }}>{done ? "✓" : "•"}</span>;
}

export function SetupBanner() {
  const { data } = useProjectResource<OnboardingStatus>(api.onboardingStatus);
  if (!data) return null;

  if (data.first_request.seen) return null;

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-head">
        <h3>Finish connecting Varsten</h3>
        <div className="right"><span className="pill neutral">Waiting for first request</span></div>
      </div>
      <div style={{ padding: "0 12px 12px" }}>
        <div className="es">No traffic yet. Send one request through Varsten to light up your dashboard.</div>
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          <div><Tick done={data.has_api_key} />Varsten API key</div>
          <div><Tick done={data.has_provider_connection} />Provider connection</div>
          <div><Tick done={false} />First request received</div>
        </div>
        <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 12 }}>
          <Link className="btn primary" href="/onboarding">Finish setup</Link>
          <a className="btn" href={SETUP_CALL_HREF}>Book setup call</a>
        </div>
      </div>
    </div>
  );
}
