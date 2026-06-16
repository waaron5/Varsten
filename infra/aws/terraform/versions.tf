terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state. Create the bucket + lock table once, out of band, then fill in
  # via `terraform init -backend-config=...` per environment so staging and prod
  # never share state. Left partial on purpose.
  backend "s3" {
    # bucket         = "varsten-tfstate"
    # key            = "app/terraform.tfstate"
    # region         = "us-east-1"
    # dynamodb_table = "varsten-tflock"
    # encrypt        = true
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
