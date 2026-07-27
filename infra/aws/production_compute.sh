#!/usr/bin/env bash
set -euo pipefail

region="${AWS_REGION:-us-east-1}"
service_name="${VARSTEN_SERVICE_NAME:-varsten-production}"
action="${1:-status}"

service_arn="$(
  aws apprunner list-services \
    --region "$region" \
    --query "ServiceSummaryList[?ServiceName=='${service_name}'].ServiceArn | [0]" \
    --output text
)"

if [[ -z "$service_arn" || "$service_arn" == "None" ]]; then
  echo "App Runner service not found: ${service_name} (${region})" >&2
  exit 1
fi

status() {
  aws apprunner describe-service \
    --service-arn "$service_arn" \
    --region "$region" \
    --query "Service.Status" \
    --output text
}

wait_for_status() {
  local wanted="$1"
  local current
  for _ in {1..60}; do
    current="$(status)"
    if [[ "$current" == "$wanted" ]]; then
      echo "$current"
      return 0
    fi
    sleep 5
  done
  echo "Timed out waiting for ${service_name} to reach ${wanted}; current status: $(status)" >&2
  return 1
}

case "$action" in
  sleep)
    current="$(status)"
    if [[ "$current" == "PAUSED" ]]; then
      echo "PAUSED"
      exit 0
    fi
    aws apprunner pause-service \
      --service-arn "$service_arn" \
      --region "$region" \
      --query "OperationId" \
      --output text
    wait_for_status "PAUSED"
    ;;
  wake)
    echo "Waking production. Apply the current Terraform configuration after resume" >&2
    echo "so database-free health checks and SCHEDULER_ENABLED=false are live." >&2
    current="$(status)"
    if [[ "$current" == "RUNNING" ]]; then
      echo "RUNNING"
      exit 0
    fi
    aws apprunner resume-service \
      --service-arn "$service_arn" \
      --region "$region" \
      --query "OperationId" \
      --output text
    wait_for_status "RUNNING"
    ;;
  status)
    status
    ;;
  *)
    echo "Usage: $0 {sleep|wake|status}" >&2
    exit 2
    ;;
esac
