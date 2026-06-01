import type {
  Breakdown,
  BreakdownDimension,
  MetricsOverview,
  SpendTrend,
  UsageEvent,
  UsageEventFilters,
  UsageEventPage,
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
  apiKey: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}/v1${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${apiKey}`,
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

export const api = {
  overview: (apiKey: string) =>
    request<MetricsOverview>("/metrics/overview", apiKey),

  spendTrend: (apiKey: string, days = 30) =>
    request<SpendTrend>(`/metrics/spend-trend${qs({ days })}`, apiKey),

  breakdown: (
    apiKey: string,
    dimension: BreakdownDimension,
    opts: { days?: number; limit?: number } = {},
  ) =>
    request<Breakdown>(
      `/metrics/breakdown${qs({ dimension, ...opts })}`,
      apiKey,
    ),

  usageEvents: (apiKey: string, filters: UsageEventFilters = {}) =>
    request<UsageEventPage>(`/usage-events${qs({ ...filters })}`, apiKey),

  usageEvent: (apiKey: string, id: string) =>
    request<UsageEvent>(`/usage-events/${id}`, apiKey),
};
