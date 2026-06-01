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


settings = Settings()
