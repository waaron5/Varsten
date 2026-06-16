output "api_url" {
  description = "Public HTTPS URL of the App Runner service. Point the frontend's NEXT_PUBLIC_API_BASE at this."
  value       = "https://${aws_apprunner_service.api.service_url}"
}

output "ecr_repository_url" {
  description = "Push the API image here before deploying (docker build/push, then set image_tag)."
  value       = aws_ecr_repository.api.repository_url
}

output "rds_endpoint" {
  description = "RDS endpoint (host:port). Private; reachable only from the API."
  value       = aws_db_instance.main.endpoint
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}
