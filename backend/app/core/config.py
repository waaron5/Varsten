from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Origins allowed to call the API from a browser (the Next.js dev/prod app).
    cors_origins: list[str] = ["http://localhost:3000"]
    # Auth0 tenant for validating dashboard access tokens. Empty until configured;
    # require_user returns 503 if these are unset so the failure is explicit.
    auth0_domain: str = ""
    auth0_audience: str = ""
    # Source for the price sync loader. A maintained public dataset, overridable
    # via env so prices are never literals in code. Defaults to the LiteLLM feed.
    pricing_feed_url: str = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )
    # How long a project's recommendations are served from storage before a read
    # triggers a recompute. Keeps the month-scan off the hot read path; lower for
    # fresher recommendations, higher for less recompute under load.
    recommendations_max_age_seconds: int = 600

    # --- Phase 1 inline proxy (OpenAI only) ---
    # Upstream OpenAI base URL (overridable to point at a mock in tests).
    openai_base_url: str = "https://api.openai.com"
    # Temporary env-vaulted provider keys: project_id -> OpenAI API key. Supplied
    # as JSON in PROXY_OPENAI_KEYS, e.g. {"<project-uuid>": "sk-..."}. A real
    # per-tenant KMS-backed vault replaces this later.
    proxy_openai_keys: dict[str, str] = {}
    # The only active optimization lever in Phase 1. The other four are bypassed.
    semantic_cache_enabled: bool = True
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

    # --- Eval / replay harness (Track B) ---
    # The shadow-evaluation loop that proves a cheaper-model swap is safe on a
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
    eval_replay_max_samples: int = 50
    # Objective pass rate a run must clear to mark a recommendation auto-eligible.
    eval_objective_pass_threshold: float = 0.95
    # Judge model for the subjective (pairwise) tier. Runs off-path only; its
    # verdict drives approve-mode and never triggers auto-rollback.
    eval_judge_model: str = "gpt-4o-mini"

    # --- Observability ---
    log_level: str = "INFO"
    # JSON logs in production; set false for plain human-readable logs locally.
    log_json: bool = True
    # Sentry error tracking. Empty DSN disables it entirely (no-op).
    sentry_dsn: str = ""
    sentry_environment: str = "development"


settings = Settings()
