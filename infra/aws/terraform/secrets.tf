// Secrets. Two kinds:
//   1. The database URL, assembled here from the RDS endpoint + generated password
//      and stored so the app reads DATABASE_URL from Secrets Manager.
//   2. Per-project provider keys, written at runtime by the app's Connections flow
//      under varsten/<env>/provider-keys/<project_id>/<provider>. Terraform only
//      grants access to that path (iam.tf); it never holds provider-key values.

resource "aws_secretsmanager_secret" "database_url" {
  name        = "varsten/${var.environment}/database-url"
  description = "Postgres connection string for the Varsten API"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+psycopg://%s:%s@%s:%s/%s",
    aws_db_instance.main.username,
    random_password.db.result,
    aws_db_instance.main.address,
    aws_db_instance.main.port,
    aws_db_instance.main.db_name,
  )
}
