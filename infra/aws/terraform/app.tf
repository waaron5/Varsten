// The API on AWS App Runner: a managed container host (the AWS analogue of Cloud
// Run), chosen over hand-rolled ECS at this stage per CLAUDE.md. App Runner owns
// TLS, autoscaling, health checks, and zero-downtime deploys + one-click rollback
// between revisions. The image comes from ECR. Egress is the default public path,
// which reaches the managed Postgres (Neon, SSL) and the upstream providers -- no
// VPC connector needed while the database is an external managed service.

resource "aws_ecr_repository" "api" {
  name                 = "varsten-api"
  image_tag_mutability = "IMMUTABLE" # a tag (git SHA) always means one image; safe rollback
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

locals {
  # Redis is wired only when a URL is supplied. Provisioning the Redis cluster
  # itself (ElastiCache / Upstash) is deliberately left to the operator: it is a
  # recurring cost, so this config consumes a URL rather than creating the cluster.
  redis_enabled = var.rate_limit_redis_url != ""

  app_env_vars = merge(
    {
      APP_ENV                         = var.environment
      PROVIDER_KEY_BACKEND            = "secretsmanager"
      PROVIDER_KEY_AWS_REGION         = var.region
      PROVIDER_KEY_SECRET_PREFIX      = "varsten"
      PROVIDER_KEY_SECRET_ENVIRONMENT = var.environment
      PROVIDER_KEY_KMS_KEY_ID         = aws_kms_key.provider_keys.arn
      PROVIDER_KEY_CACHE_TTL_SECONDS  = "30"
      PROXY_DEFAULT_PROVIDER          = "openai"
      SCHEDULER_ENABLED               = "true"
      # Multi-instance coordination: each background sweep takes a per-job Postgres
      # advisory lock, so only one instance runs a given sweep at a time. Required
      # whenever app_max_instances > 1.
      SCHEDULER_ADVISORY_LOCK_ENABLED = "true"
      # Bound the per-instance database connection draw (see infra README).
      DB_POOL_SIZE                      = tostring(var.db_pool_size)
      DB_MAX_OVERFLOW                   = tostring(var.db_max_overflow)
      CORS_ORIGINS                      = var.cors_origins
      AUTH0_DOMAIN                      = var.auth0_domain
      AUTH0_AUDIENCE                    = var.auth0_audience
      SELF_SERVE_BILLING_ENABLED        = tostring(var.self_serve_billing_enabled)
      ALLOW_DISABLED_SELF_SERVE_BILLING = tostring(var.allow_disabled_self_serve_billing)
      BILLING_SUCCESS_URL               = var.billing_success_url
      BILLING_CANCEL_URL                = var.billing_cancel_url
      SENTRY_ENVIRONMENT                = var.environment
      LOG_JSON                          = "true"
    },
    # Shared rate limiter across instances only when Redis is configured; otherwise
    # the app keeps its in-memory limiter (per-instance, fail-open).
    local.redis_enabled ? { RATE_LIMIT_BACKEND = "redis" } : {}
  )

  app_secrets = merge(
    {
      DATABASE_URL = aws_secretsmanager_secret.database_url.arn
      SENTRY_DSN   = aws_secretsmanager_secret.sentry_dsn.arn
    },
    var.self_serve_billing_enabled ? {
      STRIPE_SECRET_KEY      = aws_secretsmanager_secret.stripe_secret_key[0].arn
      STRIPE_PUBLISHABLE_KEY = aws_secretsmanager_secret.stripe_publishable_key[0].arn
      STRIPE_WEBHOOK_SECRET  = aws_secretsmanager_secret.stripe_webhook_secret[0].arn
    } : {},
    local.redis_enabled ? { RATE_LIMIT_REDIS_URL = aws_secretsmanager_secret.rate_limit_redis_url[0].arn } : {}
  )
}

# Redis URL for the shared rate limiter, stored as a secret like DATABASE_URL.
# Created only when a URL is supplied. The instance role's existing
# varsten/<env>/* read grant (iam.tf) already covers it.
resource "aws_secretsmanager_secret" "rate_limit_redis_url" {
  count       = local.redis_enabled ? 1 : 0
  name        = "varsten/${var.environment}/rate-limit-redis-url"
  description = "Redis URL for the Varsten shared rate limiter"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "rate_limit_redis_url" {
  count         = local.redis_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.rate_limit_redis_url[0].id
  secret_string = var.rate_limit_redis_url
}

resource "aws_apprunner_service" "api" {
  service_name = "varsten-${var.environment}"

  source_configuration {
    auto_deployments_enabled = false # deploys are explicit (image_tag change + apply)

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port = "8000"

        # Built in locals so the Redis rate-limiter settings can be added
        # conditionally on var.rate_limit_redis_url. Note on horizontal scaling:
        # the provider-key TTL cache (app/proxy/keys.py) and the per-project circuit
        # breaker (app/proxy/circuit.py) are INTENTIONALLY per-instance in-memory
        # stores. They are performance optimisations, not shared state: each instance
        # warms its own provider-key cache, and a per-instance breaker that trips on
        # that instance's own observed upstream failures is correct and avoids a
        # shared-store round-trip on the hot path. They need no coordination when
        # app_max_instances > 1.
        runtime_environment_variables = local.app_env_vars

        # Pulled from Secrets Manager at start, never rendered into Terraform state
        # as plaintext beyond the secret resources themselves.
        runtime_environment_secrets = local.app_secrets
      }
    }
  }

  instance_configuration {
    cpu               = var.app_cpu
    memory            = var.app_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/health/ready" # readiness: in rotation only when the DB is reachable
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 3
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.main.arn

  lifecycle {
    precondition {
      condition = (
        !var.self_serve_billing_enabled ||
        (
          var.stripe_secret_key != "" &&
          var.stripe_publishable_key != "" &&
          var.stripe_webhook_secret != ""
        )
      )
      error_message = "Stripe keys/secrets must be set when self_serve_billing_enabled=true."
    }
  }
}

resource "aws_apprunner_auto_scaling_configuration_version" "main" {
  auto_scaling_configuration_name = "varsten-${var.environment}"
  min_size                        = var.app_min_instances
  max_size                        = var.app_max_instances
}

# Sentry DSN as a secret so it is injected the same managed way as DATABASE_URL.
resource "aws_secretsmanager_secret" "sentry_dsn" {
  name        = "varsten/${var.environment}/sentry-dsn"
  description = "Sentry DSN for the Varsten API"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "sentry_dsn" {
  secret_id     = aws_secretsmanager_secret.sentry_dsn.id
  secret_string = var.sentry_dsn
}
