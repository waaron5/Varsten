"use client";

import { useEffect, useState } from "react";
import { useUser } from "@auth0/nextjs-auth0";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import { currentOnboardingIntent } from "@/lib/onboardingIntent";
import type { OnboardingStatus } from "@/lib/types";
import { useSession } from "./session";

export function StartRedirect() {
  return (
    <RequireSession>
      <StartBody />
    </RequireSession>
  );
}

function StartBody() {
  const router = useRouter();
  const { profile } = useSession();
  const { user } = useUser();
  const { data, getToken, reload } = useProjectResource<OnboardingStatus>(["onboardingStatus"], api.onboardingStatus);
  const intent = currentOnboardingIntent();
  const [intentApplied, setIntentApplied] = useState(false);

  useEffect(() => {
    if (!intent) return;
    const email = profile?.email ?? user?.email ?? "";
    if (!email) return;
    let cancelled = false;
    void (async () => {
      try {
        await api.syncUser(await getToken(), {
          email,
          name: profile?.name ?? user?.name ?? null,
          onboarding_intent: intent,
        });
        await reload();
      } finally {
        if (!cancelled) setIntentApplied(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, intent, profile?.email, profile?.name, reload, user?.email, user?.name]);

  useEffect(() => {
    if (!data || (intent && !intentApplied)) return;
    router.replace(data.onboarding_completed_at ? "/dashboard" : "/onboarding");
  }, [data, intent, intentApplied, router]);

  return (
    <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
      <div className="empty">
        <div className="spinner" />
        <div className="es">Setting up your workspace…</div>
      </div>
    </div>
  );
}
