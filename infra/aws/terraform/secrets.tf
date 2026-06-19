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
