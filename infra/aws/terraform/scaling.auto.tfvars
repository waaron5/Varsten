# Committed scaling inputs (secret-free), auto-loaded by Terraform in every
# environment. This exists so CI and local agree: CI does not see the gitignored
# terraform.tfvars, so without this it would fall back to the variables.tf default
# (app_max_instances = 4) and try to replace the live App Runner autoscaling
# revision (max_size 1 -> 4).
#
# Keep max at 1 until the rate limiter moves to a shared store (set
# RATE_LIMIT_REDIS_URL); raising it to >1 without that degrades rate limiting to
# per-instance. See variables.tf:app_max_instances.
app_min_instances = 1
app_max_instances = 1
