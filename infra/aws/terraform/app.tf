// The API on AWS App Runner: a managed container host (the AWS analogue of Cloud
// Run), chosen over hand-rolled ECS at this stage per CLAUDE.md. App Runner owns
// TLS, autoscaling, health checks, and zero-downtime deploys + one-click rollback
// between revisions. The image comes from ECR; a VPC connector lets it reach the
// private RDS instance.

resource "aws_ecr_repository" "api" {
  name                 = "varsten-api"
  image_tag_mutability = "IMMUTABLE" # a tag (git SHA) always means one image; safe rollback
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_apprunner_vpc_connector" "main" {
  vpc_connector_name = "varsten-${var.environment}"
  subnets            = data.aws_subnets.default.ids
  security_groups    = [aws_security_group.app_egress.id]
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

        runtime_environment_variables = {
          APP_ENV                       = var.environment
          PROVIDER_KEY_BACKEND          = "secretsmanager"
          PROVIDER_KEY_AWS_REGION       = var.region
          PROVIDER_KEY_SECRET_PREFIX    = "varsten"
          PROVIDER_KEY_SECRET_ENVIRONMENT = var.environment
          PROXY_DEFAULT_PROVIDER        = "openai"
          SCHEDULER_ENABLED             = "true"
          CORS_ORIGINS                  = var.cors_origins
          AUTH0_DOMAIN                  = var.auth0_domain
          AUTH0_AUDIENCE                = var.auth0_audience
          SENTRY_ENVIRONMENT            = var.environment
          LOG_JSON                      = "true"
        }

        # Pulled from Secrets Manager at start, never rendered into Terraform state
        # as plaintext beyond the secret resources themselves.
        runtime_environment_secrets = {
          DATABASE_URL = aws_secretsmanager_secret.database_url.arn
          SENTRY_DSN   = aws_secretsmanager_secret.sentry_dsn.arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.app_cpu
    memory            = var.app_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.main.arn
    }
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
}

resource "aws_secretsmanager_secret_version" "sentry_dsn" {
  secret_id     = aws_secretsmanager_secret.sentry_dsn.id
  secret_string = var.sentry_dsn
}
