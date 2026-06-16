"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import type { OnboardingStatus } from "@/lib/types";

export function StartRedirect() {
  return (
    <RequireSession>
      <StartBody />
    </RequireSession>
  );
}

function StartBody() {
  const router = useRouter();
  const { data } = useProjectResource<OnboardingStatus>(api.onboardingStatus);

  useEffect(() => {
    if (!data) return;
    router.replace(data.onboarding_completed_at ? "/command-center" : "/onboarding");
  }, [data, router]);

  return (
    <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
      <div className="empty">
        <div className="spinner" />
        <div className="es">Setting up your workspace…</div>
      </div>
    </div>
  );
}
