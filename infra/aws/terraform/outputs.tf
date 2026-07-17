output "api_url" {
  description = "Public HTTPS URL of the App Runner service. Point the frontend's NEXT_PUBLIC_API_BASE at this (or at the api.varsten.ai custom domain once configured)."
  value       = "https://${aws_apprunner_service.api.service_url}"
}

output "ecr_repository_url" {
  description = "Push the API image here before deploying (docker build/push, then set image_tag)."
  value       = aws_ecr_repository.api.repository_url
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "provider_key_kms_key_arn" {
  description = "Customer-managed KMS key used only for provider API-key secrets."
  value       = aws_kms_key.provider_keys.arn
}
