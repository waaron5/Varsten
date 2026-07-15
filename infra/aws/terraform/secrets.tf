// Secrets. Two kinds:
//   1. The database URL (the managed-Postgres connection string supplied in
//      var.database_url), stored so the app reads DATABASE_URL from Secrets Manager
//      rather than a plaintext env var.
//   2. Per-project provider keys, written at runtime by the app's Connections flow
//      under varsten/<env>/provider-keys/<project_id>/<provider>. Terraform only
//      grants access to that path (iam.tf); it never holds provider-key values.

resource "aws_secretsmanager_secret" "database_url" {
  name        = "varsten/${var.environment}/database-url"
  description = "Postgres connection string for the Varsten API"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = var.database_url
}

resource "aws_secretsmanager_secret" "stripe_secret_key" {
  count       = var.self_serve_billing_enabled ? 1 : 0
  name        = "varsten/${var.environment}/stripe-secret-key"
  description = "Stripe live secret key for Varsten self-serve billing"
}

resource "aws_secretsmanager_secret_version" "stripe_secret_key" {
  count         = var.self_serve_billing_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.stripe_secret_key[0].id
  secret_string = var.stripe_secret_key
}

resource "aws_secretsmanager_secret" "stripe_publishable_key" {
  count       = var.self_serve_billing_enabled ? 1 : 0
  name        = "varsten/${var.environment}/stripe-publishable-key"
  description = "Stripe live publishable key for Varsten self-serve billing"
}

resource "aws_secretsmanager_secret_version" "stripe_publishable_key" {
  count         = var.self_serve_billing_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.stripe_publishable_key[0].id
  secret_string = var.stripe_publishable_key
}

resource "aws_secretsmanager_secret" "stripe_webhook_secret" {
  count       = var.self_serve_billing_enabled ? 1 : 0
  name        = "varsten/${var.environment}/stripe-webhook-secret"
  description = "Stripe webhook signing secret for Varsten self-serve billing"
}

resource "aws_secretsmanager_secret_version" "stripe_webhook_secret" {
  count         = var.self_serve_billing_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.stripe_webhook_secret[0].id
  secret_string = var.stripe_webhook_secret
}
