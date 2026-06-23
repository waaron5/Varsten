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
  description = "Minimum warm instances App Runner keeps provisioned."
  type        = number
  default     = 1
}

variable "app_max_instances" {
  description = "Maximum instances App Runner can scale to. Safe above 1 now that the cross-instance constraints are handled: the scheduler takes a Postgres advisory lock per job (SCHEDULER_ADVISORY_LOCK_ENABLED) and the rate limiter uses a shared Redis backend when RATE_LIMIT_REDIS_URL is set. Without Redis the rate limiter degrades to per-instance counting (fail-open, not fatal). Size the database/pooler for (db_pool_size + db_max_overflow) * 2 * app_max_instances connections."
  type        = number
  default     = 4
}

variable "rate_limit_redis_url" {
  description = "Redis connection URL for the shared rate limiter (redis://:password@host:6379/0). REQUIRED for globally-correct rate limiting once app_max_instances > 1; leave empty to accept per-instance limiting (each instance enforces its own window, fail-open). Stored as a secret. Provision a small managed Redis (ElastiCache / Upstash) -- this is the one new recurring cost of horizontal scaling."
  type        = string
  default     = ""
  sensitive   = true
}

variable "db_pool_size" {
  description = "SQLAlchemy pool_size per engine (sync + async). Per-instance steady-state connections is db_pool_size * 2."
  type        = number
  default     = 5
}

variable "db_max_overflow" {
  description = "SQLAlchemy max_overflow per engine (burst above pool_size). Per-instance worst case is (db_pool_size + db_max_overflow) * 2 connections; multiply by app_max_instances to size the server/pooler."
  type        = number
  default     = 5
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
