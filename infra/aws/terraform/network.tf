// Networking. Uses the account's default VPC + subnets so the stack is deployable
// without standing up a full custom VPC first. RDS is NOT publicly accessible; it
// only accepts connections from the App Runner VPC connector's security group, so
// the database is reachable from the API and from nothing else on the internet.
// Move to dedicated private subnets when compliance requires it (see runbook).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Egress SG attached to the App Runner VPC connector. App Runner makes outbound
# connections from this SG; RDS allows 5432 from exactly this SG and nothing else.
resource "aws_security_group" "app_egress" {
  name        = "varsten-${var.environment}-app-egress"
  description = "App Runner VPC connector egress"
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "All outbound (upstream providers, RDS, Secrets Manager)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name        = "varsten-${var.environment}-db"
  description = "Postgres, reachable only from the App Runner connector SG"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from the API only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_egress.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
