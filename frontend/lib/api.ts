import type {
  AdminBillingSecurity,
  AdminConnections,
  AdminTeam,
  ApiKeyCreated,
  ApiKeySummary,
  AlertRule,
  AnalysisCustomers,
  AnalysisModels,
  AnalysisSpend,
  AlertRuleCreate,
  ActiveRoute,
  ActiveTrim,
  AutomationLever,
  BatchJob,
  BudgetRule,
  BudgetRuleCreate,
  Breakdown,
  BreakdownDimension,
  Dashboard,
  DashboardPeriod,
  DashboardSnapshot,
  Entitlements,
  EvalConfig,
  EvalRunSummary,
  GoldenSampleInput,
  LeverConfig,
  LeverName,
  MetricsOverview,
  MonthlyReport,
  OnboardingStatus,
  ProofAttribution,
  ProofDataQuality,
  ProviderConnection,
  ProofSavings,
  Project,
  ProxyTraffic,
  QualityGuardrail,
  QualityGuardrailCreate,
  Recommendation,
  RecommendationStatus,
  SavingsTrend,
  SpendTrend,
  UsageEvent,
  UsageEventFilters,
  UsageEventPage,
  UserProfile,
} from "./types";
import type { OnboardingIntent } from "./onboardingIntent";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 15000;

export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function apiErrorMessage(body: Record<string, unknown>, fallback: string): { detail: string; code: string | null } {
  if (typeof body.detail === "string") return { detail: body.detail, code: null };
  if (body.detail && typeof body.detail === "object") {
    const obj = body.detail as { message?: unknown; code?: unknown };
    return {
      detail: typeof obj.message === "string" ? obj.message : JSON.stringify(body.detail),
      code: typeof obj.code === "string" ? obj.code : null,
    };
  }
  if (typeof body.message === "string") return { detail: body.message, code: null };
  return { detail: fallback, code: null };
}

async function parseApiError(res: Response): Promise<{ detail: string; rawDetail: unknown; code: string | null }> {
  try {
    const body = (await res.json()) as Record<string, unknown>;
    const parsed = apiErrorMessage(body, res.statusText);
    return { ...parsed, rawDetail: body.detail ?? body };
  } catch {
    return { detail: res.statusText, rawDetail: null, code: null };
  }
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const { detail, rawDetail, code } = await parseApiError(res);
    throw new ApiError(res.status, detail, rawDetail, code);
  }
  return res.json() as Promise<T>;
}

async function request<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  return jsonOrThrow<T>(await fetchWithTimeout(`${BASE}/v1${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  }));
}

async function publicRequest<T>(path: string): Promise<T> {
  return jsonOrThrow<T>(await fetchWithTimeout(`${BASE}/v1${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
  }));
}

async function fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut || (error instanceof Error && error.name === "AbortError")) {
      throw new ApiError(408, "API request timed out. Check that the Varsten backend is running and reachable.");
    }
    if (error instanceof TypeError) {
      throw new ApiError(
        0,
        `Could not reach the Varsten API at ${BASE}. Start the backend on port 8000 or set NEXT_PUBLIC_API_BASE to the running API URL.`,
      );
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// Reads carry the bearer token plus, for an Auth0 session, the active project_id.
// With an API key the project is implied by the key, so project_id is omitted.
function readPath(
  path: string,
  projectId: string | undefined,
  params: Record<string, string | number | undefined> = {},
): string {
  return `${path}${qs({ project_id: projectId, ...params })}`;
}

export const api = {
  // --- session bootstrap (Auth0 token) ---
  syncUser: (token: string, body: { email: string; name: string | null; onboarding_intent?: OnboardingIntent }) =>
    request<UserProfile>("/auth/sync", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  projects: (token: string) => request<Project[]>("/projects", token),

  createProject: (token: string, orgId: string, name: string) =>
    request<Project>(`/organizations/${orgId}/projects`, token, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  // --- reads (Auth0 session + projectId, or an API key) ---
  overview: (token: string, projectId?: string) =>
    request<MetricsOverview>(readPath("/metrics/overview", projectId), token),

  // --- self-serve onboarding ---
  entitlements: (token: string, projectId: string | undefined) =>
    request<Entitlements>(readPath("/entitlements", projectId), token),

  onboardingStatus: (token: string, projectId: string | undefined) =>
    request<OnboardingStatus>(readPath("/onboarding/status", projectId), token),

  completeOnboarding: (token: string, projectId: string | undefined) =>
    request<{ onboarding_completed_at: string | null }>(
      readPath("/onboarding/complete", projectId),
      token,
      { method: "POST" },
    ),

  onboardingEvent: (
    token: string,
    projectId: string | undefined,
    event: "snippet_viewed" | "dashboard_entered",
  ) =>
    request<{ event: string; recorded_at: string | null }>(
      readPath("/onboarding/event", projectId),
      token,
      { method: "POST", body: JSON.stringify({ event }) },
    ),

  // --- self-serve upgrade (Stripe). Org-level, not project-scoped. ---
  billingCheckoutSession: (token: string, orgId: string) =>
    request<{ url: string }>(`/organizations/${orgId}/billing/checkout-session`, token, {
      method: "POST",
    }),

  billingPortalSession: (token: string, orgId: string) =>
    request<{ url: string }>(`/organizations/${orgId}/billing/portal-session`, token, {
      method: "POST",
    }),

  spendTrend: (token: string, projectId: string | undefined, days = 30) =>
    request<SpendTrend>(readPath("/metrics/spend-trend", projectId, { days }), token),

  savingsTrend: (
    token: string,
    projectId: string | undefined,
    opts: number | { days?: number; period?: "rolling" | "mtd" } = 30,
  ) => {
    const params = typeof opts === "number" ? { days: opts } : opts;
    return request<SavingsTrend>(readPath("/metrics/savings-trend", projectId, params), token);
  },

  proxyTraffic: (token: string, projectId: string | undefined, days = 30) =>
    request<ProxyTraffic>(readPath("/metrics/proxy-traffic", projectId, { days }), token),

  breakdown: (
    token: string,
    projectId: string | undefined,
    dimension: BreakdownDimension,
    opts: { days?: number; period?: "rolling" | "mtd"; limit?: number } = {},
  ) =>
    request<Breakdown>(
      readPath("/metrics/breakdown", projectId, { dimension, ...opts }),
      token,
    ),

  usageEvents: (
    token: string,
    projectId: string | undefined,
    filters: UsageEventFilters = {},
  ) => request<UsageEventPage>(readPath("/usage-events", projectId, { ...filters }), token),

  usageEvent: (token: string, projectId: string | undefined, id: string) =>
    request<UsageEvent>(readPath(`/usage-events/${id}`, projectId), token),

  recommendations: (
    token: string,
    projectId: string | undefined,
    status: RecommendationStatus = "open",
  ) =>
    request<Recommendation[]>(
      readPath("/recommendations", projectId, { status }),
      token,
    ),

  dashboard: (token: string, projectId: string | undefined) =>
    request<Dashboard>(readPath("/dashboard", projectId), token),

  dashboardSnapshot: (token: string, projectId: string | undefined, opts: { period: DashboardPeriod }) =>
    request<DashboardSnapshot>(readPath("/dashboard/snapshot", projectId, { ...opts }), token),

  // Returns the CSV body so the caller can trigger a browser download. Same
  // authoritative computation as the snapshot, scoped to the caller's project.
  dashboardExportCsv: async (token: string, projectId: string | undefined, opts: { period: DashboardPeriod }) => {
    const res = await fetchWithTimeout(`${BASE}/v1${readPath("/dashboard/export", projectId, { ...opts })}`, {
      headers: { authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new ApiError(res.status, "Dashboard export failed.");
    return res.text();
  },

  engineRecommendations: (
    token: string,
    projectId: string | undefined,
    status: RecommendationStatus = "open",
  ) =>
    request<Recommendation[]>(
      readPath("/engine/recommendations", projectId, { status }),
      token,
    ),

  updateEngineRecommendation: (
    token: string,
    projectId: string | undefined,
    id: string,
    status: RecommendationStatus,
  ) =>
    request<Recommendation>(
      readPath(`/engine/recommendations/${id}`, projectId),
      token,
      {
        method: "PATCH",
        body: JSON.stringify({ status }),
      },
    ),

  engineLevers: (token: string, projectId: string | undefined) =>
    request<LeverConfig[]>(readPath("/engine/levers", projectId), token),

  engineRoutes: (token: string, projectId: string | undefined) =>
    request<ActiveRoute[]>(readPath("/engine/routes", projectId), token),

  updateEngineRoute: (
    token: string,
    projectId: string | undefined,
    ruleId: string,
    body: { enabled?: boolean; holdback_percent?: string },
  ) =>
    request<{ id: string; enabled: boolean; holdback_percent: string | null }>(
      readPath(`/engine/routes/${ruleId}`, projectId),
      token,
      { method: "PATCH", body: JSON.stringify(body) },
    ),

  checkRouteDrift: (token: string, projectId: string | undefined) =>
    request<{ rolled_back: { route: string }[] }>(
      readPath("/engine/routes/check-drift", projectId),
      token,
      { method: "POST" },
    ),

  engineTrims: (token: string, projectId: string | undefined) =>
    request<ActiveTrim[]>(readPath("/engine/trims", projectId), token),

  updateEngineTrim: (
    token: string,
    projectId: string | undefined,
    policyId: string,
    body: { enabled?: boolean; holdback_percent?: string },
  ) =>
    request<{ id: string; enabled: boolean; holdback_percent: string | null }>(
      readPath(`/engine/trims/${policyId}`, projectId),
      token,
      { method: "PATCH", body: JSON.stringify(body) },
    ),

  engineBatches: (token: string, projectId: string | undefined) =>
    request<BatchJob[]>(readPath("/engine/batches", projectId), token),

  updateLever: (
    token: string,
    projectId: string | undefined,
    lever: LeverName | string,
    body: { enabled?: boolean; automation_mode?: "auto" | "approve" },
  ) =>
    request<LeverConfig>(readPath(`/engine/levers/${lever}`, projectId), token, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  engineAutomation: (token: string, projectId: string | undefined) =>
    request<AutomationLever[]>(readPath("/engine/automation", projectId), token),

  proofSavings: (token: string, projectId: string | undefined) =>
    request<ProofSavings>(readPath("/proof/savings", projectId), token),

  proofAttribution: (token: string, projectId: string | undefined) =>
    request<ProofAttribution>(readPath("/proof/attribution", projectId), token),

  proofDataQuality: (token: string, projectId: string | undefined) =>
    request<ProofDataQuality>(readPath("/proof/data-quality", projectId), token),

  guardrailsQuality: (token: string, projectId: string | undefined) =>
    request<QualityGuardrail[]>(readPath("/guardrails/quality", projectId), token),

  createQualityGuardrail: (
    token: string,
    projectId: string | undefined,
    body: QualityGuardrailCreate,
  ) =>
    request<QualityGuardrail>(readPath("/guardrails/quality", projectId), token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  guardrailsBudgets: (token: string, projectId: string | undefined) =>
    request<BudgetRule[]>(readPath("/guardrails/budgets", projectId), token),

  createBudgetRule: (
    token: string,
    projectId: string | undefined,
    body: BudgetRuleCreate,
  ) =>
    request<BudgetRule>(readPath("/guardrails/budgets", projectId), token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  guardrailsAlerts: (token: string, projectId: string | undefined) =>
    request<AlertRule[]>(readPath("/guardrails/alerts", projectId), token),

  createAlertRule: (
    token: string,
    projectId: string | undefined,
    body: AlertRuleCreate,
  ) =>
    request<AlertRule>(readPath("/guardrails/alerts", projectId), token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  analysisSpend: (token: string, projectId: string | undefined) =>
    request<AnalysisSpend>(readPath("/analysis/spend", projectId), token),

  analysisCustomers: (token: string, projectId: string | undefined) =>
    request<AnalysisCustomers>(readPath("/analysis/customers", projectId), token),

  analysisModels: (token: string, projectId: string | undefined) =>
    request<AnalysisModels>(readPath("/analysis/models", projectId), token),

  adminConnections: (token: string, projectId: string | undefined) =>
    request<AdminConnections>(readPath("/admin/connections", projectId), token),

  upsertProviderConnection: (
    token: string,
    projectId: string | undefined,
    provider: string,
    apiKey: string,
  ) =>
    request<ProviderConnection>(
      readPath(`/admin/connections/${provider}`, projectId),
      token,
      {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      },
    ),

  connectProjectProvider: (
    token: string,
    projectId: string,
    provider: string,
    apiKey: string,
  ) =>
    request<ProviderConnection>(`/projects/${projectId}/connections`, token, {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),

  disconnectProviderConnection: (
    token: string,
    projectId: string | undefined,
    provider: string,
  ) =>
    request<ProviderConnection>(
      readPath(`/admin/connections/${provider}`, projectId),
      token,
      { method: "DELETE" },
    ),

  adminTeam: (token: string, projectId: string | undefined) =>
    request<AdminTeam>(readPath("/admin/team", projectId), token),

  adminBillingSecurity: (token: string, projectId: string | undefined) =>
    request<AdminBillingSecurity>(readPath("/admin/billing-security", projectId), token),

  reports: (token: string, projectId: string | undefined) =>
    request<MonthlyReport[]>(readPath("/reports", projectId), token),

  createReport: (token: string, projectId: string | undefined) =>
    request<MonthlyReport>(readPath("/reports", projectId), token, { method: "POST" }),

  updateReport: (
    token: string,
    projectId: string | undefined,
    id: string,
    status: "draft" | "published",
  ) =>
    request<MonthlyReport>(readPath(`/reports/${id}`, projectId), token, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  publicReport: (shareToken: string) =>
    publicRequest<MonthlyReport>(`/public/reports/${shareToken}`),

  updateRecommendation: (
    token: string,
    id: string,
    status: RecommendationStatus,
  ) =>
    request<Recommendation>(`/recommendations/${id}`, token, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  // Trigger a shadow eval for a gated (model-swap) recommendation. Runs off-path
  // in a background worker; poll engineRecommendations for the updated verdict.
  evaluateRecommendation: (token: string, id: string) =>
    request<EvalRunSummary>(`/recommendations/${id}/evaluate`, token, {
      method: "POST",
    }),

  // --- eval harness config (capture opt-in + golden corpus) ---
  evalConfig: (token: string, projectId: string | undefined) =>
    request<EvalConfig>(readPath("/evals/config", projectId), token),

  updateEvalCapture: (token: string, projectId: string | undefined, enabled: boolean) =>
    request<{ eval_capture_enabled: boolean }>(readPath("/evals/capture-config", projectId), token, {
      method: "POST",
      body: JSON.stringify({ eval_capture_enabled: enabled }),
    }),

  uploadGoldenSamples: (
    token: string,
    projectId: string | undefined,
    samples: GoldenSampleInput[],
  ) =>
    request<{ created: number }>(readPath("/evals/golden", projectId), token, {
      method: "POST",
      body: JSON.stringify({ samples }),
    }),

  // --- API key management (for a project) ---
  listApiKeys: (token: string, projectId: string) =>
    request<ApiKeySummary[]>(`/projects/${projectId}/api-keys`, token),

  createApiKey: (token: string, projectId: string, name: string) =>
    request<ApiKeyCreated>(`/projects/${projectId}/api-keys`, token, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  revokeApiKey: (token: string, apiKeyId: string) =>
    request<ApiKeySummary>(`/api-keys/${apiKeyId}`, token, { method: "DELETE" }),
};
