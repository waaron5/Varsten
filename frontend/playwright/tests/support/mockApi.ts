import type { Page, Route, Request } from "playwright/test";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
export const ORG_ID = "org_e2e_maya";
export const PROJECT_ID = "proj_e2e_production";
export const NOW = "2026-06-23T19:00:00.000Z";

type JsonObject = Record<string, unknown>;

export interface MockState {
  profile: JsonObject;
  projects: JsonObject[];
  onboarding: JsonObject;
  entitlements: JsonObject;
  dashboardSnapshot: JsonObject;
  proofSavings: JsonObject;
  usageEvents: JsonObject;
  calls: Record<string, number>;
  upstreamFailures: JsonObject[];
  // Self-serve billing toggle: mirrors SELF_SERVE_BILLING_ENABLED on the backend.
  // false -> checkout/portal return 503 (frontend shows the contact fallback).
  billingEnabled: boolean;
  checkoutUrl: string;
  portalUrl: string;
  proxyHandler?: (request: Request, body: JsonObject, state: MockState) => Promise<MockProxyResponse> | MockProxyResponse;
}

export interface MockProxyResponse {
  status?: number;
  body: JsonObject;
  headers?: Record<string, string>;
}

function jsonHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "access-control-allow-headers": "authorization,content-type,x-varsten-metadata",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "access-control-allow-origin": "*",
    "access-control-expose-headers": "x-varsten-mode,x-varsten-request-id,x-varsten-routed",
    "content-type": "application/json",
    ...extra,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200, headers: Record<string, string> = {}) {
  await route.fulfill({
    status,
    headers: jsonHeaders(headers),
    body: JSON.stringify(body),
  });
}

async function postJson(request: Request): Promise<JsonObject> {
  try {
    return request.postDataJSON() as JsonObject;
  } catch {
    return {};
  }
}

function increment(state: MockState, key: string): void {
  state.calls[key] = (state.calls[key] ?? 0) + 1;
}

interface MockRouteContext {
  route: Route;
  request: Request;
  pathname: string;
  method: string;
  state: MockState;
}

type MockApiHandler = (ctx: MockRouteContext) => Promise<boolean>;

function matches(ctx: MockRouteContext, method: string, pathname: string): boolean {
  return ctx.method === method && ctx.pathname === pathname;
}

async function handleCorsPreflight({ route, method, pathname }: MockRouteContext): Promise<boolean> {
  if (method !== "OPTIONS" || !pathname.startsWith("/v1/")) return false;
  await route.fulfill({ status: 204, headers: jsonHeaders() });
  return true;
}

async function handleAuthAndProjects(ctx: MockRouteContext): Promise<boolean> {
  const { route, request, state } = ctx;
  if (matches(ctx, "POST", "/v1/auth/sync")) {
    increment(state, "authSync");
    const body = await postJson(request);
    if (typeof body.onboarding_intent === "string") {
      increment(state, `authSync:${body.onboarding_intent}`);
    }
    await fulfillJson(route, state.profile);
    return true;
  }
  if (matches(ctx, "GET", "/v1/projects")) {
    increment(state, "projects");
    await fulfillJson(route, state.projects);
    return true;
  }
  if (!matches(ctx, "POST", `/v1/organizations/${ORG_ID}/projects`)) return false;
  increment(state, "createProject");
  const body = await postJson(request);
  const project = createProject({ name: String(body.name ?? "Production") });
  state.projects = [project];
  state.onboarding = { ...state.onboarding, has_project: true, project_id: project.id, project_name: project.name };
  await fulfillJson(route, project, 201);
  return true;
}

async function handleOnboarding(ctx: MockRouteContext): Promise<boolean> {
  const { route, request, state } = ctx;
  if (matches(ctx, "GET", "/v1/onboarding/status")) {
    increment(state, "onboardingStatus");
    await fulfillJson(route, state.onboarding);
    return true;
  }
  if (matches(ctx, "POST", "/v1/onboarding/complete")) {
    increment(state, "completeOnboarding");
    state.onboarding = { ...state.onboarding, onboarding_completed_at: NOW };
    await fulfillJson(route, { onboarding_completed_at: NOW });
    return true;
  }
  if (matches(ctx, "POST", `/v1/projects/${PROJECT_ID}/connections`)) {
    increment(state, "connectProvider");
    const body = await postJson(request);
    await fulfillJson(route, markProviderConnected(state, String(body.provider ?? "openai")));
    return true;
  }
  if (matches(ctx, "POST", "/v1/onboarding/event")) {
    increment(state, "onboardingEvent");
    const body = await postJson(request);
    const field = body.event === "dashboard_entered" ? "dashboard_entered" : "integration_snippet_viewed";
    state.onboarding = { ...state.onboarding, [field]: true };
    increment(state, `event:${String(body.event)}`);
    await fulfillJson(route, { event: body.event, recorded_at: NOW });
    return true;
  }
  return false;
}

async function handleBilling(ctx: MockRouteContext): Promise<boolean> {
  const { route, state } = ctx;
  const checkout = matches(ctx, "POST", `/v1/organizations/${ORG_ID}/billing/checkout-session`);
  const portal = matches(ctx, "POST", `/v1/organizations/${ORG_ID}/billing/portal-session`);
  if (!checkout && !portal) return false;
  increment(state, checkout ? "billingCheckout" : "billingPortal");
  if (!state.billingEnabled) {
    await fulfillJson(
      route,
      { detail: { code: "billing_disabled", message: "Self-serve billing is not enabled." } },
      503,
    );
    return true;
  }
  await fulfillJson(route, { url: checkout ? state.checkoutUrl : state.portalUrl });
  return true;
}

async function handleApiKeys(ctx: MockRouteContext): Promise<boolean> {
  if (!matches(ctx, "POST", `/v1/projects/${PROJECT_ID}/api-keys`)) return false;
  increment(ctx.state, "createApiKey");
  ctx.state.onboarding = { ...ctx.state.onboarding, has_api_key: true };
  await fulfillJson(ctx.route, {
    id: "key_e2e_default",
    project_id: PROJECT_ID,
    name: "default",
    key_prefix: "vk_test",
    plaintext_key: "vk_test_e2e_first_request",
    last_used_at: null,
    revoked_at: null,
    created_at: NOW,
  }, 201);
  return true;
}

async function handleReadModels(ctx: MockRouteContext): Promise<boolean> {
  const reads: Record<string, [keyof MockState, string]> = {
    "/v1/dashboard/snapshot": ["dashboardSnapshot", "dashboardSnapshot"],
    "/v1/entitlements": ["entitlements", "entitlements"],
    "/v1/proof/savings": ["proofSavings", "proofSavings"],
    "/v1/usage-events": ["usageEvents", "usageEvents"],
  };
  const match = reads[ctx.pathname];
  if (ctx.method !== "GET" || !match) return false;
  const [stateKey, callKey] = match;
  increment(ctx.state, callKey);
  await fulfillJson(ctx.route, ctx.state[stateKey]);
  return true;
}

async function handleProxy(ctx: MockRouteContext): Promise<boolean> {
  const { route, request, state } = ctx;
  if (!matches(ctx, "POST", "/v1/chat/completions")) return false;
  increment(state, "proxy");
  const body = await postJson(request);
  const response = state.proxyHandler
    ? await state.proxyHandler(request, body, state)
    : await defaultProxyHandler(request, body, state);
  await fulfillJson(route, response.body, response.status ?? 200, response.headers ?? {});
  return true;
}

const MOCK_API_HANDLERS: MockApiHandler[] = [
  handleCorsPreflight,
  handleAuthAndProjects,
  handleOnboarding,
  handleBilling,
  handleApiKeys,
  handleReadModels,
  handleProxy,
];

export function createProject(overrides: JsonObject = {}): JsonObject {
  return {
    id: PROJECT_ID,
    organization_id: ORG_ID,
    name: "Production",
    is_demo: false,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

export function createProfile(overrides: JsonObject = {}): JsonObject {
  return {
    id: "user_e2e_maya",
    email: "maya@enterprise.example",
    name: "Maya Chen",
    organizations: [
      {
        id: ORG_ID,
        name: "Maya AI Co",
        monthly_spend_budget_usd: "100000.00",
        created_at: NOW,
        updated_at: NOW,
      },
    ],
    ...overrides,
  };
}

export function createEntitlements(overrides: JsonObject = {}): JsonObject {
  return {
    plan_tier: "performance",
    observe_only: false,
    observe_only_reason: null,
    quota: {
      monthly_requests: 42,
      monthly_request_limit: 100000,
      requests_remaining: 99958,
    },
    trial: {
      trial_ends_at: "2026-07-07T19:00:00.000Z",
      trial_expired: false,
    },
    features: {
      apply_recommendations: true,
      enable_levers: true,
      enable_routing: true,
      enable_caching: true,
      enable_trimming: true,
      use_batching: true,
      guardrail_automation: true,
      submit_batches: true,
      advanced_proof: true,
      advanced_reports: true,
      extended_retention: true,
    },
    ...overrides,
  };
}

export function createOnboardingStatus(overrides: JsonObject = {}): JsonObject {
  return {
    project_id: PROJECT_ID,
    project_name: "Production",
    plan_tier: "performance",
    observe_only: false,
    onboarding_completed_at: null,
    has_project: true,
    has_api_key: false,
    has_provider_connection: false,
    integration_snippet_viewed: false,
    dashboard_entered: false,
    provider_connections: [],
    first_request: {
      seen: false,
      request_count: 0,
      metadata_quality: {
        level: "none",
        message: "Add metadata headers to make savings attribution board-ready.",
      },
    },
    checklist: [
      { key: "has_api_key", complete: false },
      { key: "has_provider_connection", complete: false },
      { key: "integration_snippet_viewed", complete: false },
      { key: "first_request", complete: false },
      { key: "dashboard_entered", complete: false },
    ],
    ...overrides,
  };
}

export function createUsageEvent(overrides: JsonObject = {}): JsonObject {
  return {
    id: `evt_${Math.random().toString(16).slice(2)}`,
    project_id: PROJECT_ID,
    organization_id: ORG_ID,
    api_key_id: "key_e2e_default",
    provider: "openai",
    model: "gpt-4o-mini",
    operation: "chat_completions",
    external_user_id: "user_123",
    workflow: "support_reply",
    request_type: "chat_completion",
    feature: "support",
    customer_id: "cust_acme",
    user_id: null,
    team: "support",
    department: "customer_ops",
    environment: "production",
    input_tokens: 1200,
    output_tokens: 320,
    cached_input_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 1520,
    cost_usd: "0.018000",
    reported_cost_usd: null,
    cost_source: "catalog",
    pricing_status: "priced",
    price_version_id: "price_e2e",
    currency: "USD",
    status: "ok",
    success: true,
    error_code: null,
    latency_ms: 173,
    metadata: {
      proxy: true,
    },
    event_timestamp: NOW,
    occurred_at: NOW,
    received_at: NOW,
    ...overrides,
  };
}

export function createDashboardSnapshot(overrides: JsonObject = {}): JsonObject {
  const base = {
    period: "month",
    granularity: "day",
    period_start: "2026-06-01T00:00:00.000Z",
    period_end: "2026-07-01T00:00:00.000Z",
    label: "June 2026",
    mode: "measured",
    fee_percent: "0.25",
    gross_savings_usd: "2000.00",
    kpis: [
      {
        key: "net_saved",
        label: "Net Realized Savings",
        detail: "Verified savings retained after Varsten's performance fee.",
        value: "1500.00",
        delta: { current: "1500.00", previous: "1200.00", delta_pct: "0.25" },
        tone: "brand",
      },
      {
        key: "gross_saved",
        label: "Gross Savings",
        detail: "Total cost eliminated before the performance fee is applied.",
        value: "2000.00",
        delta: { current: "2000.00", previous: "1600.00", delta_pct: "0.25" },
        tone: null,
      },
      {
        key: "without_varsten",
        label: "Baseline Cost",
        detail: "Projected spend at provider list pricing, without Varsten.",
        value: "8000.00",
        delta: { current: "8000.00", previous: "7600.00", delta_pct: "0.0526" },
        tone: null,
      },
      {
        key: "actual_spend",
        label: "Actual Spend",
        detail: "Amount paid directly to providers this period.",
        value: "6000.00",
        delta: { current: "6000.00", previous: "6000.00", delta_pct: "0" },
        tone: null,
      },
    ],
    savings_trend: [
      { date: "2026-06-21", optimized_usd: "1900.00", saved_usd: "600.00", baseline_usd: "2500.00" },
      { date: "2026-06-22", optimized_usd: "2100.00", saved_usd: "700.00", baseline_usd: "2800.00" },
      { date: "2026-06-23", optimized_usd: "2000.00", saved_usd: "700.00", baseline_usd: "2700.00" },
    ],
    trend_stats: {
      avg_spend_per_bucket_usd: "2000.00",
      avg_saved_per_bucket_usd: "666.67",
      effective_savings_rate: "0.25",
    },
    levers: [
      {
        lever: "prompt_cache",
        label: "Prompt cache",
        enabled: true,
        status: "Active",
        value_usd: "1200.00",
        share: "0.60",
        source: "measured",
      },
      {
        lever: "model_downshift",
        label: "Model downshift",
        enabled: true,
        status: "Active",
        value_usd: "800.00",
        share: "0.40",
        source: "measured",
      },
    ],
    drivers: {
      actual_total_usd: "6000.00",
      team: [
        { key: "support", label: "Support", spend_usd: "3600.00", share: "0.60" },
        { key: "sales", label: "Sales", spend_usd: "2400.00", share: "0.40" },
      ],
      feature: [
        { key: "support_reply", label: "Support reply", spend_usd: "4200.00", share: "0.70" },
        { key: "crm_summary", label: "CRM summary", spend_usd: "1800.00", share: "0.30" },
      ],
    },
    proof_trust: {
      score: "0.98",
      confidence_label: "High Confidence",
      confidence_note: "Every figure is audit-ready.",
      pricing_coverage: "1.00",
      attribution_share: "0.96",
      verified_savings_usd: "2000.00",
      claimed_savings_usd: "2000.00",
      measured_share: "1.00",
      measurement_method_label: "Ledger + holdback",
      has_direct_ledger: true,
      has_ab_holdback: true,
    },
    fallback_coverage: [
      { provider: "openai", label: "OpenAI", sdk_enabled: true, sdk_client: "varsten-openai/0.1.0", key_configured: true, status: "SDK enabled" },
      { provider: "anthropic", label: "Anthropic", sdk_enabled: false, sdk_client: null, key_configured: false, status: "Not enabled" },
      { provider: "gemini", label: "Gemini", sdk_enabled: false, sdk_client: null, key_configured: false, status: "Not enabled" },
    ],
  };
  return { ...base, ...overrides };
}

export function createProofSavings(overrides: JsonObject = {}): JsonObject {
  const direct = 1200;
  const holdback = 800;
  const verified = direct + holdback;
  const fee = 500;
  const net = verified - fee;
  const base = {
    plan_tier: "performance",
    period_start: "2026-06-01T00:00:00.000Z",
    period_end: "2026-07-01T00:00:00.000Z",
    observed_spend_usd: "6000.00",
    estimated: {
      label: "Estimated impact of applied optimizations (modeled, not measured)",
      gross_savings_usd: String(verified),
      net_savings_usd: String(net),
      varsten_fee_usd: String(fee),
      counterfactual_spend_usd: "8000.00",
      open_opportunity_usd: "0.00",
      open_opportunity_gross_usd: "0.00",
      open_opportunity_fee_usd: "0.00",
      open_opportunity_net_usd: "0.00",
    },
    verified: {
      label: "Verified savings, measured from the ledger",
      direct_measured_usd: String(direct),
      holdback_measured_usd: String(holdback),
      holdback_ci_low_usd: "700.00",
      holdback_ci_high_usd: "900.00",
      holdback_has_signal: true,
      verified_savings_usd: String(verified),
      verified_fee_usd: String(fee),
      verified_net_usd: String(net),
      billable_savings_usd: String(verified),
    },
    counterfactual_spend_usd: "8000.00",
    actual_spend_usd: "6000.00",
    gross_savings_usd: String(verified),
    varsten_fee_usd: String(fee),
    net_savings_usd: String(net),
    measurement_note:
      "Verified savings are measured: direct ledger savings plus holdback A/B savings.",
  };
  return { ...base, ...overrides };
}

export function createMockState(overrides: Partial<MockState> = {}): MockState {
  const project = createProject();
  return {
    profile: createProfile(),
    projects: [project],
    onboarding: createOnboardingStatus(),
    entitlements: createEntitlements(),
    dashboardSnapshot: createDashboardSnapshot(),
    proofSavings: createProofSavings(),
    usageEvents: {
      items: [],
      limit: 50,
      offset: 0,
      has_more: false,
    },
    upstreamFailures: [],
    billingEnabled: false,
    checkoutUrl: "/upgrade?checkout=stripe-redirect",
    portalUrl: "/upgrade?portal=stripe-redirect",
    calls: {},
    ...overrides,
  };
}

function markProviderConnected(state: MockState, provider: string): JsonObject {
  const connection = {
    provider,
    status: "connected",
    last_verified_at: NOW,
    last_error: null,
  };
  const existing = (state.onboarding.provider_connections as JsonObject[]).filter((c) => c.provider !== provider);
  state.onboarding = {
    ...state.onboarding,
    has_provider_connection: true,
    provider_connections: [...existing, connection],
  };
  return {
    id: `conn_${provider}`,
    provider,
    connection_method: "vault",
    status: "connected",
    key_vaulted: true,
    last_sync_at: NOW,
    last_verified_at: NOW,
    last_error: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

function markFirstRequestSeen(state: MockState, event: JsonObject): void {
  state.onboarding = {
    ...state.onboarding,
    first_request: {
      seen: true,
      request_count: state.calls.proxy,
      request_id: event.id,
      provider: event.provider,
      model: event.model,
      cost_usd: event.cost_usd,
      cost_source: event.cost_source,
      pricing_status: event.pricing_status,
      input_tokens: event.input_tokens,
      output_tokens: event.output_tokens,
      latency_ms: event.latency_ms,
      environment: event.environment,
      feature: event.feature,
      workflow: event.workflow,
      task_type: "support_reply.billing",
      occurred_at: event.occurred_at,
      metadata_quality: {
        level: "great",
        message: "Metadata is complete enough for workflow-level proof.",
      },
    },
  };
}

async function defaultProxyHandler(_request: Request, body: JsonObject, state: MockState): Promise<MockProxyResponse> {
  const event = createUsageEvent({
    provider: "openai",
    model: String(body.model ?? "gpt-4o-mini"),
    metadata: {
      proxy: true,
      first_request: true,
    },
  });
  (state.usageEvents.items as JsonObject[]).unshift(event);
  markFirstRequestSeen(state, event);
  return {
    status: 200,
    headers: {
      "x-varsten-mode": "observe",
      "x-varsten-request-id": String(event.id),
    },
    body: {
      id: "chatcmpl_e2e_first",
      object: "chat.completion",
      created: 1782241200,
      model: event.model,
      choices: [{ index: 0, message: { role: "assistant", content: "ok" }, finish_reason: "stop" }],
      usage: { prompt_tokens: 1200, completion_tokens: 320, total_tokens: 1520 },
    },
  };
}

async function handleApiRoute(route: Route, state: MockState): Promise<boolean> {
  const request = route.request();
  const url = new URL(request.url());
  const ctx = { route, request, pathname: url.pathname, method: request.method(), state };
  if (!ctx.pathname.startsWith("/v1/")) return false;
  for (const handler of MOCK_API_HANDLERS) {
    if (await handler(ctx)) return true;
  }

  await fulfillJson(route, { detail: `Unhandled E2E API route: ${ctx.method} ${ctx.pathname}` }, 404);
  return true;
}

export async function installMockApi(page: Page, state: MockState): Promise<void> {
  await page.context().addCookies(
    ["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:3100", "http://localhost:3100"].map(
      (url) => ({
        name: "varsten_e2e_auth",
        value: "1",
        url,
      }),
    ),
  );

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === "/auth/profile") {
      await fulfillJson(route, {
        sub: "auth0|maya-enterprise",
        email: "maya@enterprise.example",
        name: "Maya Chen",
      });
      return;
    }

    if (url.pathname === "/auth/access-token") {
      await fulfillJson(route, { token: "e2e-control-plane-token" });
      return;
    }

    if (await handleApiRoute(route, state)) return;

    await route.fallback();
  });
}

export function watchClientErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

export function moneyNumber(text: string): number {
  const normalized = text.replace(/[^0-9.-]/g, "");
  return Number(normalized);
}
