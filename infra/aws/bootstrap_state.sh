#!/usr/bin/env bash
#
# Bootstrap the Terraform remote-state backend: an S3 bucket for state and a
# DynamoDB table for state locking. Run this ONCE per AWS account, BEFORE the first
# `terraform init` -- Terraform cannot create the bucket that holds its own state in
# the same run (chicken-and-egg).
#
# Idempotent: safe to re-run. Each resource is created only if missing, and the
# security settings (versioning, encryption, public-access block, TLS-only policy)
# are re-asserted every run.
#
# The defaults MUST match the backend block in terraform/versions.tf. Override via
# env vars if the bucket name (globally unique) is taken:
#   STATE_BUCKET=varsten-tfstate LOCK_TABLE=varsten-tflock AWS_REGION=us-east-1 ./bootstrap_state.sh
#
# Required IAM: s3:CreateBucket/PutBucket*, dynamodb:CreateTable/DescribeTable.

set -euo pipefail

STATE_BUCKET="${STATE_BUCKET:-varsten-tfstate}"
LOCK_TABLE="${LOCK_TABLE:-varsten-tflock}"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "Bootstrapping Terraform state backend in ${AWS_REGION}:"
echo "  S3 bucket:      ${STATE_BUCKET}"
echo "  DynamoDB table: ${LOCK_TABLE}"

# --- S3 state bucket ----------------------------------------------------------
if aws s3api head-bucket --bucket "${STATE_BUCKET}" 2>/dev/null; then
  echo "S3 bucket ${STATE_BUCKET} already exists; re-asserting settings."
else
  echo "Creating S3 bucket ${STATE_BUCKET}."
  # us-east-1 must NOT pass a LocationConstraint; every other region must.
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${STATE_BUCKET}" --region "${AWS_REGION}"
  else
    aws s3api create-bucket --bucket "${STATE_BUCKET}" --region "${AWS_REGION}" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
  fi
fi

# Versioning: keep state history so a bad apply can be rolled back.
aws s3api put-bucket-versioning \
  --bucket "${STATE_BUCKET}" \
  --versioning-configuration Status=Enabled

# Default encryption at rest (SSE-S3 / AES256). No KMS key to manage.
aws s3api put-bucket-encryption \
  --bucket "${STATE_BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

# Block all public access -- state contains secrets in plaintext.
aws s3api put-public-access-block \
  --bucket "${STATE_BUCKET}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Deny any non-TLS access to the bucket.
aws s3api put-bucket-policy \
  --bucket "${STATE_BUCKET}" \
  --policy "$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::${STATE_BUCKET}",
        "arn:aws:s3:::${STATE_BUCKET}/*"
      ],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    }
  ]
}
JSON
)"

# --- DynamoDB lock table ------------------------------------------------------
if aws dynamodb describe-table --table-name "${LOCK_TABLE}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  echo "DynamoDB table ${LOCK_TABLE} already exists; nothing to do."
else
  echo "Creating DynamoDB table ${LOCK_TABLE}."
  # LockID (String) is the primary key the S3 backend expects. PAY_PER_REQUEST so
  # there is no idle capacity cost for a low-write lock table.
  aws dynamodb create-table \
    --table-name "${LOCK_TABLE}" \
    --region "${AWS_REGION}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
  aws dynamodb wait table-exists --table-name "${LOCK_TABLE}" --region "${AWS_REGION}"
fi

echo "Done. Now run, from infra/aws/terraform:"
echo "  terraform init"
echo "  terraform workspace new staging   # or: terraform workspace select staging"
