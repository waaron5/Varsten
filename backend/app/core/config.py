from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Origins allowed to call the API from a browser (the Next.js dev/prod app).
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
