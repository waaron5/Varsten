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
    # Upstream request timeout (seconds) for the non-streaming path.
    proxy_upstream_timeout_seconds: float = 60.0
    # Global kill switch. When true, every project's traffic bypasses all Varsten
    # optimization and forwards straight to OpenAI (still metered). The operator's
    # emergency lever; a per-project switch lives on the project row.
    proxy_kill_switch: bool = False


settings = Settings()
