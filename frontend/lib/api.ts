import type {
  ApiKeyCreated,
  ApiKeySummary,
  Breakdown,
  BreakdownDimension,
  MetricsOverview,
  Project,
  SpendTrend,
  UsageEvent,
  UsageEventFilters,
  UsageEventPage,
  UserProfile,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}/v1${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
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
  syncUser: (token: string, body: { email: string; name: string | null }) =>
    request<UserProfile>("/auth/sync", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  projects: (token: string) => request<Project[]>("/projects", token),

  createProject: async (orgId: string, name: string): Promise<Project> => {
    const res = await fetch(`${BASE}/v1/organizations/${orgId}/projects`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new ApiError(res.status, "could not create project");
    return res.json() as Promise<Project>;
  },

  // --- reads (Auth0 session + projectId, or an API key) ---
  overview: (token: string, projectId?: string) =>
    request<MetricsOverview>(readPath("/metrics/overview", projectId), token),

  spendTrend: (token: string, projectId: string | undefined, days = 30) =>
    request<SpendTrend>(readPath("/metrics/spend-trend", projectId, { days }), token),

  breakdown: (
    token: string,
    projectId: string | undefined,
    dimension: BreakdownDimension,
    opts: { days?: number; limit?: number } = {},
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
