variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment. Drives resource names, the secret prefix, and APP_ENV. Use a separate Terraform workspace/state per environment so staging and production never collide."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be 'staging' or 'production'."
  }
}

variable "image_tag" {
  description = "Container image tag to deploy (e.g. a git SHA). App Runner redeploys when this changes; keep it pinned, never 'latest', so rollback is just re-applying the previous tag."
  type        = string
}

variable "app_cpu" {
  description = "App Runner vCPU units (e.g. 1024 = 1 vCPU)."
  type        = string
  default     = "1024"
}

variable "app_memory" {
  description = "App Runner memory in MB."
  type        = string
  default     = "2048"
}

variable "app_min_instances" {
  description = "Minimum warm instances. NOTE: the in-process scheduler and rate limiter assume a single instance; keep max=1 until those move to a shared store / external runner (see CLAUDE.md and the runbook)."
  type        = number
  default     = 1
}

variable "app_max_instances" {
  description = "Maximum instances. Keep at 1 in Phase 1 (single-instance constraint)."
  type        = number
  default     = 1
}

variable "database_url" {
  description = "SQLAlchemy/psycopg connection string for the managed Postgres (Neon now, RDS later). Must use the psycopg driver and SSL, e.g. postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require. Stored in Secrets Manager, never in plaintext env. Sensitive."
  type        = string
  sensitive   = true
}

variable "cors_origins" {
  description = "JSON array of allowed browser origins, passed to the API as CORS_ORIGINS. Must be the real frontend origin(s), never localhost (the app refuses to boot otherwise)."
  type        = string
}

variable "auth0_domain" {
  type = string
}

variable "auth0_audience" {
  type = string
}

variable "sentry_dsn" {
  description = "Sentry DSN. Required: the app refuses to boot in production without it."
  type        = string
  sensitive   = true
}
