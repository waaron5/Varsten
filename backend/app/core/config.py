from tempfile import gettempdir

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # SQLAlchemy connection pool sizing, per engine (there are two: sync + async).
    # Worst-case connections held by one app instance is
    # (db_pool_size + db_max_overflow) * 2. Multiply by app_max_instances to size
    # the database / pooler. When running more than one instance, point DATABASE_URL
    # at a pooled endpoint (Neon pooler / PgBouncer / RDS Proxy) so these per-instance
    # pools multiplex onto far fewer server connections (see infra/aws/README.md).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Recycle a pooled connection after this many seconds, so connections severed by
    # the managed Postgres / pooler idle timeout are replaced instead of erroring.
    db_pool_recycle_seconds: int = 1800
    # Check a connection's liveness before handing it out (cheap), so a stale pooled
    # connection never surfaces as a request error after a failover or pooler reset.
    db_pool_pre_ping: bool = True
    # Origins allowed to call the API from a browser (the Next.js dev/prod app).
    cors_origins: list[str] = ["http://localhost:3000"]
    # Auth0 tenant for validating dashboard access tokens. Empty until configured;
    # require_user returns 503 if these are unset so the failure is explicit.
    auth0_domain: str = ""
    auth0_audience: str = ""
    # Source for the price sync loader. A maintained public dataset, overridable
    # via env so prices are never literals in code. Defaults to the LiteLLM feed.
    pricing_feed_url: str = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    )
    # How long a project's recommendations are served from storage before a read
    # triggers a recompute. Keeps the month-scan off the hot read path; lower for
    # fresher recommendations, higher for less recompute under load.
    recommendations_max_age_seconds: int = 600
    # Founder/operator accounts allowed to use provisioning and validation tools.
    # Set as JSON in env, e.g. OPERATOR_ADMIN_EMAILS='["aaron@varsten.ai"]'.
    operator_admin_emails: list[str] = []

    # --- Inline proxy provider keys / routing ---
    # Upstream provider for proxied traffic. Resolved through the provider adapter
    # registry. Phase 1 ships only "openai"; multi-provider support registers
    # additional providers behind the same seam.
    proxy_default_provider: str = "openai"
    # Upstream OpenAI base URL (overridable to point at a mock in tests).
    openai_base_url: str = "https://api.openai.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    # Legacy env-vaulted OpenAI keys: project_id -> OpenAI API key. Supplied as
    # JSON in PROXY_OPENAI_KEYS, e.g. {"<project-uuid>": "sk-..."}. Retained for
    # local/dev and rollback compatibility.
    proxy_openai_keys: dict[str, str] = {}
    # Generic dev/test env key map: provider -> project_id -> key, e.g.
    # PROXY_PROVIDER_KEYS='{"anthropic":{"<project-uuid>":"sk-ant-..."}}'.
    # Production uses provider_key_backend="secretsmanager" instead.
    proxy_provider_keys: dict[str, dict[str, str]] = {}
    proxy_anthropic_keys: dict[str, str] = {}
    proxy_gemini_keys: dict[str, str] = {}
    # Production provider-key backend. "env" preserves local/dev compatibility;
    # production should set "secretsmanager".
    provider_key_backend: str = "env"
    # Mandatory hot-path memory cache for decrypted provider keys. Secrets Manager
    # lookups must never happen on every proxied request.
    provider_key_cache_ttl_seconds: int = 300
    provider_key_cache_maxsize: int = 4096
    provider_key_secret_prefix: str = "varsten"
    provider_key_secret_environment: str = "development"
    provider_key_aws_region: str = ""
    # Optional local development fallback for self-serve key storage. Production
    # still requires Secrets Manager; when provider_key_backend="localdb", provider
    # keys are encrypted with this Fernet/base-secret value and stored on the
    # provider_connections row.
    provider_key_local_encryption_key: str = ""
    # Master switch for the proxy cache (exact-hash lookup + store). This is the
    # Day One lever: byte-identical repeats serve from the store at $0 with zero
    # added latency (no embedding call). Turn this off to disable caching entirely.
    proxy_cache_enabled: bool = True
    # Retention for stored cache content (the documented exception to the
    # metadata-only ledger). An entry is served and kept for this long after it is
    # written, then skipped by lookups and deleted by the purge sweep. Default 7
    # days: long enough for repeat-heavy traffic to hit, short enough that stored
    # responses do not accumulate indefinitely. Lower it for stricter retention.
    proxy_cache_ttl_seconds: int = 604800
    # How often the purge sweep deletes past-due cache entries. In-process, single
    # instance (mirrors the other scheduler jobs).
    cache_purge_interval_seconds: int = 3600
    # The semantic layer ON TOP of the exact-hash cache: embed the prompt and match
    # the nearest stored answer within a distance threshold. Requires
    # proxy_cache_enabled. Off by default for Client #1 because (a) it adds an
    # embedding round-trip on the miss path and (b) near-identical tool-call JSON
    # arguments are prone to false-positive matches. Enable once an in-process
    # embedding model removes the latency and a per-route threshold is tuned.
    semantic_cache_enabled: bool = False
    # Embedding model + dimensionality for semantic-cache matching.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    # Max cosine distance for a semantic hit (0 = identical). Lower is stricter;
    # 0.08 ~ 0.92 cosine similarity, conservative to avoid serving wrong answers.
    semantic_cache_threshold: float = 0.08
    # Latency budget for the semantic-lookup embedding. It sits on the cache-miss
    # hot path (the lookup needs the query vector before it can match), so it must
    # be tightly bounded and fail open. A slow embedding skips semantic matching
    # and forwards rather than stalling the request. The proper fix in-VPC is an
    # in-process embedding model with no network hop; this bound holds until then.
    embedding_timeout_seconds: float = 2.0
    # Upstream request timeout (seconds) for the non-streaming path.
    proxy_upstream_timeout_seconds: float = 60.0
    # Connection pool for the shared upstream client. Keep-alive connections are
    # what spare a cache miss the TCP+TLS handshake; size the cap to expected
    # concurrent in-flight upstream requests.
    proxy_pool_max_connections: int = 100
    proxy_pool_max_keepalive_connections: int = 20
    # Streaming-path timeouts. read = max gap between chunks before we treat the
    # upstream as hung (the guard against pinning an event-loop slot indefinitely);
    # total = wall-clock cap on a single stream as a backstop. connect mirrors the
    # non-stream connect budget. Generous total so legitimate long generations are
    # not truncated; tighten per deployment if needed.
    proxy_stream_connect_timeout_seconds: float = 10.0
    proxy_stream_read_timeout_seconds: float = 30.0
    proxy_stream_total_timeout_seconds: float = 600.0
    # Max size of the client-supplied X-Varsten-Metadata JSON header. Larger
    # payloads are ignored (fail-open), never an error, so a misbehaving client
    # cannot bloat a ledger row or break its own request.
    proxy_metadata_max_bytes: int = 8192

    # --- Self-serve hardening: provider key validation + rate limits ---
    # Probe a provider key with a cheap authenticated call before storing it, so a
    # bad key fails at connect time with a clear message instead of failing every
    # proxied request later. Off in tests (the network probe is mocked/disabled).
    provider_key_validation_enabled: bool = True
    provider_key_validation_timeout_seconds: float = 8.0
    # In-memory fixed-window rate limits. Single-process only (not distributed):
    # with more than one app instance, move this to a shared store. Generous by
    # default; fail-open if the limiter itself errors.
    rate_limit_enabled: bool = True
    # Rate-limit backend: "memory" (per-process, dev / single-instance default) or
    # "redis" (one shared window across instances). Move to "redis" before raising
    # app_max_instances above 1, or each instance limits independently.
    rate_limit_backend: str = "memory"
    # Redis URL for rate_limit_backend="redis", e.g. redis://:password@host:6379/0.
    # Empty falls back to the in-memory limiter with a warning.
    rate_limit_redis_url: str = ""
    # Socket timeout (seconds) for the limiter's Redis calls. The limiter runs on
    # the proxy hot path, so a slow or unreachable Redis must fail open fast and
    # never stall a request; keep this small.
    rate_limit_redis_timeout_seconds: float = 0.1
    # Per Varsten API key, on the inline proxy (the public, abuse-exposed surface).
    proxy_rate_limit_per_minute: int = 600
    # Per user, on the provider-connect endpoint (cheap to abuse against providers).
    connect_rate_limit_per_minute: int = 20
    # Trial/quota soft paywall. Exceeding either limit never blocks traffic; it
    # downshifts the proxy into observe-only mode and surfaces warning headers/UI.
    free_monthly_request_limit: int = 100_000
    free_trial_days: int = 14
    # How often the trial sweep downgrades unpaid, elapsed Performance trials to Free
    # observe-only. The entitlement read path also does this lazily, so the sweep is
    # the durable-state backstop, not the only mechanism; hourly is plenty.
    trial_sweep_interval_seconds: int = 3600
    # Global kill switch. When true, every project's traffic bypasses all Varsten
    # optimization and forwards straight to OpenAI (still metered). The operator's
    # emergency lever; a per-project switch lives on the project row.
    proxy_kill_switch: bool = False

    # Per-project circuit breaker for the upstream provider. After this many
    # consecutive upstream failures the breaker opens and the proxy fails fast
    # (503) instead of making every request wait the full timeout. It probes for
    # recovery after reset_seconds. Cache hits are unaffected and still served.
    circuit_breaker_enabled: bool = True
    circuit_breaker_fail_threshold: int = 5
    circuit_breaker_reset_seconds: float = 30.0

    # In-process cache of resolved vk_ -> (project, api_key) on the proxy hot path.
    # Lets a known active key keep serving through a brief database blip instead of
    # 500ing: on a DB error the proxy serves a context resolved within this TTL.
    # Unknown/invalid keys are never cached and still fail closed. Revocation lag is
    # bounded by this TTL. 0 disables the cache.
    api_key_cache_ttl_seconds: float = 30.0

    # --- Eval / replay harness (Track B) ---
    # The shadow-evaluation loop that proves a model-downshift swap is safe on a
    # route's real traffic BEFORE it can be applied. Everything here runs async,
    # off the request hot path. Capture is opt-in per project (Project.eval_capture
    # _enabled) and globally gated here so it is off by default.
    eval_capture_enabled: bool = False
    # Fraction of cache-miss proxy traffic sampled into the replay corpus.
    eval_sample_rate: float = 0.1
    # Hard cap on stored traffic samples per route, so the content store stays
    # bounded. Oldest are evicted past this.
    eval_max_samples_per_route: int = 200
    # Retention for captured real-traffic samples. Golden samples never expire.
    eval_sample_ttl_days: int = 14
    # Minimum samples a route needs before a run yields a verdict instead of
    # "insufficient_data". Below this the recommendation stays approve-only.
    eval_min_samples: int = 20
    # How many samples a single run replays through the candidate. Caps run cost.
    eval_replay_max_samples: int = 200
    # Objective pass rate a run must clear to mark a recommendation auto-eligible.
    eval_objective_pass_threshold: float = 0.95
    # Judge model for the subjective (pairwise) tier. Runs off-path only; its
    # verdict drives approve-mode and never triggers auto-rollback.
    eval_judge_model: str = "gpt-4o-mini"
    # Append-only JSONL file for candidate loss records (golden dataset).
    # Relative paths are resolved from the repo root; override via env var.
    eval_failure_registry_path: str = "data/eval/golden_dataset_failures.jsonl"

    # --- Live quality-drift guard on the holdback ---
    # A routed (treatment) arm whose objective quality drops more than this below
    # the concurrent control arm is rolled back. Objective signal only (CLAUDE.md:
    # judge noise is never bet on for auto-rollback).
    drift_tolerance: float = 0.05
    # Master switch for automatic rollback on drift. Off -> drift is surfaced but a
    # human decides. On -> a drifted route is disabled automatically.
    drift_auto_rollback_enabled: bool = True

    # --- Batching lever data plane (async /v1/batches mirror) ---
    # Where staged batch .jsonl files live. "local" (filesystem, dev/CI) or "s3"
    # (prod). The proxy never holds the file in memory: the client uploads it to
    # storage via a pre-signed URL, and the backend streams it to OpenAI.
    batch_storage_backend: str = "local"
    # Local backend root (dev/CI). One subtree per project for tenant isolation.
    batch_local_storage_dir: str = f"{gettempdir()}/varsten-batches"
    # S3 backend settings (only read when batch_storage_backend == "s3"). Region
    # and credentials come from the standard AWS env/instance role, not from here.
    batch_s3_bucket: str = ""
    batch_s3_region: str = ""
    # Lifetime of a pre-signed upload/download URL.
    batch_presign_ttl_seconds: int = 3600
    # How long staged input/output objects are retained before cleanup. The batch
    # file is a documented content store (like the cache), so it is TTL'd.
    batch_object_ttl_hours: int = 72
    # Default completion window passed to OpenAI's Batch API.
    batch_completion_window: str = "24h"

    # --- Budget enforcement + alerts ---
    # Hard-cap enforcement in the proxy hot path. When a request's workload owner
    # (team/feature/customer) has a hard-cap budget that is exhausted this month,
    # the proxy blocks the (paid) forward. Cache hits ($0) are never blocked; the
    # check is fail-open (any error allows the request) and respects the kill switch.
    budget_enforcement_enabled: bool = True
    # Budget state is read from a short-TTL process-local cache so the hot path does
    # not sum the ledger on every request. Single-process (mirrors the other caches).
    budget_enforcement_cache_ttl_seconds: int = 30
    # How often the budget/alert sweep evaluates thresholds and delivers alerts.
    alert_sweep_interval_seconds: int = 300
    # Notification delivery. Empty config = a no-op sender that records the delivery
    # in history but sends nothing (safe default for dev/CI). Production sets these.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = "alerts@varsten.ai"
    # Per-alert Slack webhook URLs are stored on the alert rule's destination; this
    # is only the global on/off for outbound HTTP from the alert sender.
    slack_alerts_enabled: bool = True

    # --- Background scheduler ---
    # Master switch for the in-process periodic scheduler (drift sweep + batch
    # poller). Off by default so tests and one-off processes do not spawn loops;
    # production sets SCHEDULER_ENABLED=true. With more than one app instance, run
    # this on a single leader (or move to external cron) so sweeps do not overlap.
    scheduler_enabled: bool = False
    # Per-job Postgres advisory lock around each sweep so only one instance runs a
    # given job at a time. Off by default (single-instance/dev); set true whenever
    # app_max_instances > 1, or every instance runs every sweep. Fails open: a lock
    # error runs the job rather than dropping a safety sweep.
    scheduler_advisory_lock_enabled: bool = False
    # How often the quality-drift safety sweep runs across all projects.
    drift_sweep_interval_seconds: int = 300
    # How often the batch poller syncs in-flight batch jobs across all projects.
    batch_poll_interval_seconds: int = 120

    # --- Observability ---
    log_level: str = "INFO"
    # JSON logs in production; set false for plain human-readable logs locally.
    log_json: bool = True
    # Sentry error tracking. Empty DSN disables it entirely (no-op).
    sentry_dsn: str = ""
    sentry_environment: str = "development"

    # --- Deployment environment ---
    # Drives production self-checks at startup. "production" makes a misconfigured
    # deploy fail loudly at boot (validate_production) instead of silently running
    # on dev-safe defaults (no auth, env-vaulted keys, localhost CORS). Set
    # APP_ENV=production in the real environment.
    app_env: str = "development"

    # --- Self-serve billing (Stripe) ---
    # Master switch for the Stripe upgrade path. Off by default so the app boots and
    # the trial works without any Stripe config; production turns it on once keys are
    # set. When off, the checkout/portal endpoints return 503 and the webhook 404,
    # but trials, entitlements, and the sweep are unaffected.
    self_serve_billing_enabled: bool = False
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    # Signing secret for the Stripe webhook endpoint. Required to verify that an
    # inbound event genuinely came from Stripe before it can change a plan.
    stripe_webhook_secret: str = ""
    # Where Stripe Checkout returns the user after success/cancel (the dashboard
    # billing page). {CHECKOUT_SESSION_ID} is substituted by Stripe on success.
    billing_success_url: str = "https://app.varsten.ai/admin/billing-security?checkout=success"
    billing_cancel_url: str = "https://app.varsten.ai/admin/billing-security?checkout=cancel"


def _localhost_origin(origin: str) -> bool:
    o = origin.lower()
    return "localhost" in o or "127.0.0.1" in o or "0.0.0.0" in o  # nosec B104 - substring check, not a socket bind


def validate_production(s: "Settings") -> list[str]:
    """Return the list of production-readiness problems with ``s``.

    These are the dev-safe defaults that are dangerous in production: no dashboard
    auth, provider keys read from env instead of the vault, browser CORS open to
    localhost, and no error visibility. Empty list means the config is safe to
    serve a real customer. Pure function so it is unit-testable without booting.
    """
    problems: list[str] = []
    if not s.auth0_domain or not s.auth0_audience:
        problems.append("AUTH0_DOMAIN and AUTH0_AUDIENCE must be set (dashboard auth is disabled without them).")
    if s.provider_key_backend.strip().lower() != "secretsmanager":
        problems.append("PROVIDER_KEY_BACKEND must be 'secretsmanager' in production (env-vaulted keys are dev-only).")
    elif not s.provider_key_aws_region:
        problems.append("PROVIDER_KEY_AWS_REGION must be set when PROVIDER_KEY_BACKEND=secretsmanager.")
    if not s.cors_origins:
        problems.append("CORS_ORIGINS must list the real frontend origin(s).")
    elif any(_localhost_origin(o) for o in s.cors_origins):
        problems.append(f"CORS_ORIGINS must not include a localhost origin in production: {s.cors_origins}.")
    if not s.sentry_dsn:
        problems.append("SENTRY_DSN must be set in production so errors are visible.")
    if s.self_serve_billing_enabled:
        # Only enforce Stripe config when self-serve billing is actually turned on, so
        # a deploy can run safely with billing temporarily disabled.
        if not s.stripe_secret_key:
            problems.append("STRIPE_SECRET_KEY must be set when SELF_SERVE_BILLING_ENABLED=true.")
        if not s.stripe_webhook_secret:
            problems.append("STRIPE_WEBHOOK_SECRET must be set when SELF_SERVE_BILLING_ENABLED=true.")
    return problems


def assert_production_ready(s: "Settings") -> None:
    """Raise if ``s`` is unsafe to serve production traffic. Called at startup only
    when APP_ENV=production, so a bad deploy never silently degrades a customer."""
    if s.app_env.strip().lower() != "production":
        return
    problems = validate_production(s)
    if problems:
        raise RuntimeError(
            "Refusing to start: APP_ENV=production but the configuration is not production-ready:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


settings = Settings()
