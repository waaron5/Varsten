// Managed Postgres (RDS). Automated backups + point-in-time recovery are on via
// backup_retention_period > 0. Storage is encrypted; the instance is private.
// The connection string is assembled and stored in Secrets Manager (secrets.tf)
// so the application reads it the same way it reads provider keys.

resource "random_password" "db" {
  length  = 32
  special = false # keep the URL free of characters that need escaping
}

resource "aws_db_subnet_group" "main" {
  name       = "varsten-${var.environment}"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "main" {
  identifier     = "varsten-${var.environment}"
  engine         = "postgres"
  engine_version = "16"

  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 5 # storage autoscaling headroom
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "varsten"
  username = "varsten"
  password = random_password.db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  # Backups + PITR. retention > 0 is what enables restore-to-any-second.
  backup_retention_period   = var.db_backup_retention_days
  backup_window             = "07:00-08:00"
  maintenance_window        = "Mon:08:30-Mon:09:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "varsten-${var.environment}-final"

  auto_minor_version_upgrade = true
  apply_immediately          = false

  # pgvector lives in the standard Postgres image; the semantic cache needs it.
  # `CREATE EXTENSION vector;` is run by the app's migrations, not here.
}
