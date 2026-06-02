// Mirrors the FastAPI Pydantic response models. Numeric money/token fields that
// the backend serializes as Decimal arrive as strings; parse at the edge.

export interface UsageEvent {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  operation: string;
  external_user_id: string | null;
  workflow: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: string;
  currency: string;
  metadata: Record<string, unknown>;
  received_at: string;
}

export interface UsageEventPage {
  items: UsageEvent[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface MetricsOverview {
  spend_today: string;
  spend_month: string;
  requests_today: number;
  requests_month: number;
  input_tokens_today: number;
  output_tokens_today: number;
  avg_cost_per_request_today: string | null;
}

export interface SpendTrendPoint {
  date: string;
  spend: string;
  requests: number;
}

export interface SpendTrend {
  granularity: string;
  points: SpendTrendPoint[];
}

export type BreakdownDimension =
  | "provider"
  | "model"
  | "workflow"
  | "external_user_id";

export interface BreakdownRow {
  key: string | null;
  spend: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Breakdown {
  dimension: BreakdownDimension;
  rows: BreakdownRow[];
}

export interface Organization {
  id: string;
  name: string;
  monthly_spend_budget_usd: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  organizations: Organization[];
}

export interface ApiKeySummary {
  id: string;
  project_id: string;
  name: string;
  key_prefix: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeySummary {
  // The plaintext key, returned only once at creation.
  plaintext_key: string;
}

export interface UsageEventFilters {
  provider?: string;
  model?: string;
  workflow?: string;
  external_user_id?: string;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
}
