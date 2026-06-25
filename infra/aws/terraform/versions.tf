terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60.0"
    }
  }

  # Remote state in S3 with DynamoDB locking, so CI/CD and multiple operators share
  # one source of truth and concurrent applies can never corrupt state. The bucket
  # and lock table must already exist -- Terraform cannot create the bucket that
  # holds its own state in the same run -- so run ./bootstrap_state.sh ONCE before
  # the first `terraform init` (see infra/aws/README.md).
  #
  # Per-environment isolation comes from Terraform workspaces: each workspace
  # (staging, production) keeps its state at env:/<workspace>/app/terraform.tfstate
  # in this same bucket, so one backend config serves every environment.
  #
  # These values are static (a backend block cannot use variables/locals). If the
  # bucket name is already taken globally, change it in BOTH this block and
  # bootstrap_state.sh.
  backend "s3" {
    bucket         = "varsten-tfstate"
    key            = "app/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "varsten-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "varsten"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
