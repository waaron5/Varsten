// Mirrors the FastAPI Pydantic response models. Numeric money/token fields that
// the backend serializes as Decimal arrive as strings; parse at the edge.

export interface UsageEvent {
  id: string;
  project_id: string;
  organization_id: string;
  api_key_id: string | null;
  provider: string;
  model: string;
  operation: string;
  external_user_id: string | null;
  workflow: string | null;
  request_type: string | null;
  feature: string | null;
  customer_id: string | null;
  user_id: string | null;
  team: string | null;
  department: string | null;
  environment: string;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cost_usd: string | null;
  reported_cost_usd: string | null;
  cost_source: string;
  pricing_status: string;
  price_version_id: string | null;
  currency: string;
  status: string;
  success: boolean;
  error_code: string | null;
  latency_ms: number | null;
  metadata: Record<string, unknown>;
  event_timestamp: string | null;
  occurred_at: string | null;
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
  monthly_forecast_usd: string;
  monthly_budget_usd: string | null;
  budget_variance_usd: string | null;
  budget_burn_percent: string | null;
  days_elapsed_days_remaining: string;
  authoritative_spend_month: string;
  authoritative_spend_share_month: string | null;
  catalog_spend_month: string;
  override_spend_month: string;
  reported_spend_month: string;
  unknown_spend_month: string;
  priced_event_count_month: number;
  unpriced_event_count_month: number;
  unpriced_token_count_month: number;
  unpriced_event_share_month: string | null;
  metadata_quality: Record<string, string | null>;
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
  | "external_user_id"
  | "feature"
  | "customer_id"
  | "user_id"
  | "team"
  | "department"
  | "environment"
  | "request_type";

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
  feature?: string;
  customer_id?: string;
  user_id?: string;
  team?: string;
  environment?: string;
  request_type?: string;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
}

export type RecommendationStatus = "open" | "applied" | "dismissed" | "rolled_back";

export type LeverName =
  | "token_trim"
  | "semantic_cache"
  | "batching"
  | "cheaper_model"
  | "smart_routing";

export type AutomationMode = "auto" | "approve";

export interface EvalRunSummary {
  id: string;
  status: string;
  verdict: string | null;
  scorer_type: string | null;
  candidate_model: string;
  sample_count: number;
  objective_pass_rate: string | null;
  score_delta: string | null;
  score_delta_ci_low: string | null;
  score_delta_ci_high: string | null;
  cost_delta_usd: string | null;
  notes: string | null;
  completed_at: string | null;
}

export interface EvalRouteCorpus {
  route_key: string;
  traffic_samples: number;
  golden_samples: number;
}

export interface EvalConfig {
  eval_capture_enabled: boolean;
  min_samples: number;
  routes: EvalRouteCorpus[];
}

export interface GoldenSampleInput {
  route_key: string;
  messages: { role: string; content: string }[];
  expected_output: string;
  request_params?: Record<string, unknown>;
}

export interface Recommendation {
  id: string;
  organization_id: string;
  project_id: string;
  type: string;
  lever: string | null;
  target_type: string | null;
  target_key: string | null;
  title: string;
  description: string;
  rationale: string | null;
  estimated_monthly_savings_usd: string | null;
  monthly_request_volume: number | null;
  quality_delta_percent: string | null;
  measurement_method: string;
  risk_level: string;
  confidence: string;
  status: RecommendationStatus;
  related_provider: string | null;
  related_model: string | null;
  related_feature: string | null;
  related_customer_id: string | null;
  related_environment: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  // Eval gate: `gated` model-swap levers need a passing shadow eval before apply.
  gated?: boolean;
  latest_eval?: EvalRunSummary | null;
}

export interface RecommendationAction {
  id: string;
  recommendation_id: string | null;
  lever: LeverName | string | null;
  action_type: string;
  status: string;
  source: string;
  title: string;
  detail: string | null;
  estimated_savings_usd: string | number | null;
  realized_savings_usd: string | number | null;
  occurred_at: string;
}

export interface CommandCenterLiveSavings {
  spend_month: string | number;
  saved_month: string | number;
  net_saved_month: string | number;
  annual_run_rate: string | number;
  trust_score: string | number | null;
}

export interface CommandCenter {
  live_savings: CommandCenterLiveSavings;
  decision_queue: Recommendation[];
  recent_actions: RecommendationAction[];
  top_waste_now: Recommendation | null;
  requests_month: number;
}

export interface LeverConfig {
  id: string;
  organization_id: string;
  project_id: string;
  lever: LeverName | string;
  enabled: boolean;
  automation_mode: AutomationMode;
  savings_to_date_usd: string | number;
  quality_delta_percent: string | number | null;
  paused_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationLever {
  lever: LeverName | string;
  enabled: boolean;
  automation_mode: AutomationMode;
  risk_profile: string;
}

export interface ProofSavings {
  period_start: string;
  period_end: string;
  counterfactual_spend_usd: string | number;
  actual_spend_usd: string | number;
  gross_savings_usd: string | number;
  varsten_fee_usd: string | number;
  net_savings_usd: string | number;
  measurement_note: string;
}

export interface ProofAttributionRow {
  lever: LeverName | string;
  measurement_method: string;
  gross_savings_usd: string | number;
  net_savings_usd: string | number;
  actions: number;
}

export interface ProofAttribution {
  rows: ProofAttributionRow[];
  methodology: string;
}

export interface ProofDataQuality {
  requests_month: number;
  trust_score: string | number | null;
  priced_event_count: number;
  unpriced_event_count: number;
  metadata_quality: Record<string, string | number | null>;
}

export interface QualityGuardrail {
  id: string;
  route: string;
  min_model_tier: string | null;
  eval_gate: string | null;
  min_eval_score: string | number | null;
  max_latency_ms: number | null;
  auto_rollback_enabled: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface QualityGuardrailCreate {
  route: string;
  min_model_tier?: string | null;
  eval_gate?: string | null;
  min_eval_score?: string | number | null;
  max_latency_ms?: number | null;
  auto_rollback_enabled?: boolean;
  enabled?: boolean;
}

export interface BudgetRule {
  id: string;
  owner_type: "team" | "feature" | "customer";
  owner_key: string;
  monthly_budget_usd: string | number;
  hard_cap_enabled: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BudgetRuleCreate {
  owner_type: "team" | "feature" | "customer";
  owner_key: string;
  monthly_budget_usd: string | number;
  hard_cap_enabled?: boolean;
  enabled?: boolean;
}

export interface AlertRule {
  id: string;
  alert_type: string;
  threshold_usd: string | number | null;
  threshold_percent: string | number | null;
  destination_type: "email" | "slack";
  destination: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertRuleCreate {
  alert_type: string;
  threshold_usd?: string | number | null;
  threshold_percent?: string | number | null;
  destination_type: "email" | "slack";
  destination: string;
  enabled?: boolean;
}

export interface AnalysisSpendRow {
  team: string | null;
  feature: string | null;
  provider: string | null;
  spend_usd: string | number;
  requests: number;
}

export interface AnalysisSpend {
  rows: AnalysisSpendRow[];
}

export interface AnalysisCustomerRow {
  customer_id: string;
  customer_name: string | null;
  revenue_usd: string | number | null;
  ai_cost_usd: string | number;
  gross_margin_usd: string | number | null;
  status: "negative_margin" | "healthy" | "missing_revenue" | string;
  requests: number;
}

export interface AnalysisCustomers {
  rows: AnalysisCustomerRow[];
}

export interface AnalysisModelRow {
  provider: string;
  model: string;
  spend_usd: string | number;
  requests: number;
  avg_cost_per_request_usd: string | number | null;
}

export interface AnalysisModels {
  rows: AnalysisModelRow[];
}

export interface ProviderConnection {
  id: string;
  provider: string;
  connection_method: string;
  status: string;
  last_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminConnections {
  provider_connections: ProviderConnection[];
  api_keys: ApiKeySummary[];
}

export interface AdminTeamMember {
  id: string;
  user_id: string;
  email: string;
  name: string | null;
  role: string;
}

export interface AdminTeam {
  members: AdminTeamMember[];
  roles: string[];
}

export interface AdminBillingSecurity {
  plan: string;
  pricing_model: string;
  verified_savings_fee_percent: string | number | null;
  security_posture: {
    deployment_mode: string;
    content_storage: string;
    soc2_status: string;
    data_controls: string[];
  };
}

export interface MonthlyReportRecommendation {
  id: string;
  lever: string | null;
  title: string;
  risk_level: string;
  confidence: string;
  estimated_monthly_savings_usd: string | number | null;
}

export interface MonthlyReportAttributionRow {
  lever: string | null;
  measurement_method: string;
  gross_savings_usd: string | number;
  net_savings_usd: string | number;
  actions: number;
}

export interface MonthlyReport {
  id: string;
  organization_id: string;
  project_id: string;
  period_start: string;
  period_end: string;
  title: string;
  executive_summary: string;
  status: "draft" | "published" | string;
  share_token: string;
  published_at: string | null;
  counterfactual_spend_usd: string | number;
  actual_spend_usd: string | number;
  gross_savings_usd: string | number;
  varsten_fee_usd: string | number;
  net_savings_usd: string | number;
  trust_score: string | number | null;
  priced_event_count: number;
  unpriced_event_count: number;
  requests_month: number;
  metadata_quality: Record<string, string | number | null>;
  attribution_rows: MonthlyReportAttributionRow[];
  top_recommendations: MonthlyReportRecommendation[];
  created_at: string;
  updated_at: string;
}
