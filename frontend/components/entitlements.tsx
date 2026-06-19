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

const LOCKED_FEATURES = {
  advanced_proof: false,
  advanced_reports: false,
  apply_recommendations: false,
  enable_caching: false,
  enable_levers: false,
  enable_routing: false,
  enable_trimming: false,
  extended_retention: false,
  guardrail_automation: false,
  submit_batches: false,
  use_batching: false,
} satisfies Entitlements["features"];

function entitlementsValue(data: Entitlements | null, loading: boolean): EntitlementsValue {
  const features = data?.features ?? LOCKED_FEATURES;
  const planTier = data?.plan_tier ?? null;
  return {
    entitlements: data,
    loading,
    planTier,
    isPerformance: planTier === "performance",
    observeOnly: data?.observe_only === true,
    canApplyRecommendations: features.apply_recommendations,
    canEnableRouting: features.enable_routing,
    canEnableCaching: features.enable_caching,
    canEnableTrimming: features.enable_trimming,
    canUseBatching: features.use_batching,
    canUseGuardrailAutomation: features.guardrail_automation,
    canUseAdvancedProof: features.advanced_proof,
    canUseAdvancedReports: features.advanced_reports,
  };
}

export function EntitlementsProvider({ children }: { children: React.ReactNode }) {
  const { data, loading } = useProjectResource<Entitlements>(["entitlements"], api.entitlements);
  return <EntitlementsContext.Provider value={entitlementsValue(data, loading)}>{children}</EntitlementsContext.Provider>;
}

export function useEntitlements(): EntitlementsValue {
  const ctx = useContext(EntitlementsContext);
  if (!ctx) throw new Error("useEntitlements must be used within EntitlementsProvider");
  return ctx;
}
