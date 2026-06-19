terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60.0"
    }
  }

  # State is local for the first solo deploy: terraform.tfstate lives in this dir
  # (gitignored -- it holds secrets in plaintext). Move to an S3 backend with a
  # DynamoDB lock before a second operator or environment exists:
  #
  #   backend "s3" {
  #     bucket         = "varsten-tfstate"
  #     key            = "app/terraform.tfstate"
  #     region         = "us-east-1"
  #     dynamodb_table = "varsten-tflock"
  #     encrypt        = true
  #   }
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
