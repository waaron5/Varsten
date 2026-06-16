"use client";

// Shared plan/entitlement context. One fetch of GET /v1/entitlements for the
// active project, surfaced as plan tier + per-feature booleans so no component
// has to re-derive paywall logic. The backend is the source of truth and the real
// gate; this just lets the UI reflect it consistently.

import { createContext, useContext } from "react";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import type { Entitlements } from "@/lib/types";

interface EntitlementsValue {
  entitlements: Entitlements | null;
  loading: boolean;
  // null until known, so the nav can avoid flashing a wrong plan.
  planTier: string | null;
  isPerformance: boolean;
  // observeOnly is only asserted once we know the plan (false while unknown).
  observeOnly: boolean;
  canApplyRecommendations: boolean;
  canEnableRouting: boolean;
  canEnableCaching: boolean;
  canEnableTrimming: boolean;
  canUseBatching: boolean;
  canUseGuardrailAutomation: boolean;
  canUseAdvancedProof: boolean;
  canUseAdvancedReports: boolean;
}

const EntitlementsContext = createContext<EntitlementsValue | null>(null);

export function EntitlementsProvider({ children }: { children: React.ReactNode }) {
  const { data, loading } = useProjectResource<Entitlements>(api.entitlements);
  const f = data?.features;
  const value: EntitlementsValue = {
    entitlements: data,
    loading,
    planTier: data?.plan_tier ?? null,
    isPerformance: data?.plan_tier === "performance",
    observeOnly: data ? data.observe_only : false,
    // Default locked while unknown so paid controls never briefly appear unlocked.
    canApplyRecommendations: f?.apply_recommendations ?? false,
    canEnableRouting: f?.enable_routing ?? false,
    canEnableCaching: f?.enable_caching ?? false,
    canEnableTrimming: f?.enable_trimming ?? false,
    canUseBatching: f?.use_batching ?? false,
    canUseGuardrailAutomation: f?.guardrail_automation ?? false,
    canUseAdvancedProof: f?.advanced_proof ?? false,
    canUseAdvancedReports: f?.advanced_reports ?? false,
  };
  return <EntitlementsContext.Provider value={value}>{children}</EntitlementsContext.Provider>;
}

export function useEntitlements(): EntitlementsValue {
  const ctx = useContext(EntitlementsContext);
  if (!ctx) throw new Error("useEntitlements must be used within EntitlementsProvider");
  return ctx;
}
