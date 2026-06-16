// IAM. Two roles, least privilege:
//   - access role: lets App Runner pull the image from ECR.
//   - instance role: the running task's identity. It may read ONLY this
//     environment's secrets (the DB url + provider keys under varsten/<env>/*) and
//     decrypt with KMS. It cannot write or delete secrets, and cannot read another
//     environment's. This is the SOC 2-shaped boundary: the data plane can read the
//     provider key it needs and nothing more.

data "aws_caller_identity" "current" {}

# --- App Runner access role (ECR pull) ---
resource "aws_iam_role" "apprunner_access" {
  name = "varsten-${var.environment}-apprunner-access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "build.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr" {
  role       = aws_iam_role.apprunner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# --- App Runner instance role (the running task) ---
resource "aws_iam_role" "apprunner_instance" {
  name = "varsten-${var.environment}-apprunner-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "apprunner_secrets" {
  name = "varsten-${var.environment}-secrets-read"
  role = aws_iam_role.apprunner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadEnvironmentSecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:varsten/${var.environment}/*"
      },
      {
        Sid      = "DecryptSecrets"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# The Connections flow writes/deletes provider keys at runtime. Grant write ONLY
# under this environment's provider-keys path. Split from the read policy so the
# control-plane permission is explicit and auditable.
resource "aws_iam_role_policy" "apprunner_provider_key_writes" {
  name = "varsten-${var.environment}-provider-key-writes"
  role = aws_iam_role.apprunner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ManageProviderKeys"
      Effect = "Allow"
      Action = [
        "secretsmanager:CreateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DeleteSecret",
        "secretsmanager:TagResource",
      ]
      Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:varsten/${var.environment}/provider-keys/*"
    }]
  })
}
