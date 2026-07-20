locals {
  monitoring_topic_name = "varsten-${var.environment}-p0-alerts"
  monitoring_runbook    = "https://github.com/waaron5/Varsten/blob/main/docs/monitoring/ALERT_RUNBOOK.md"
  app_log_group         = "/aws/apprunner/${aws_apprunner_service.api.service_name}/${aws_apprunner_service.api.service_id}/application"
  app_dimensions = {
    ServiceName = aws_apprunner_service.api.service_name
    ServiceID   = aws_apprunner_service.api.service_id
  }

  application_log_metrics = {
    database_readiness = {
      pattern = "{ $.msg = \"readiness check failed: database unreachable\" }"
      metric  = "DatabaseReadinessFailures"
    }
    scheduler = {
      pattern = "{ $.msg = \"scheduled job failed\" }"
      metric  = "SchedulerFailures"
    }
    provider_key_read = {
      pattern = "{ $.msg = \"provider key secret read failed\" }"
      metric  = "ProviderKeyVaultFailures"
    }
    provider_key_store = {
      pattern = "{ $.msg = \"provider key store failed\" }"
      metric  = "ProviderKeyVaultFailures"
    }
    provider_key_delete = {
      pattern = "{ $.msg = \"provider key delete failed\" }"
      metric  = "ProviderKeyVaultFailures"
    }
    stripe_checkout = {
      pattern = "{ $.msg = \"stripe checkout failed\" }"
      metric  = "StripeFailures"
    }
    stripe_portal = {
      pattern = "{ $.msg = \"stripe portal failed\" }"
      metric  = "StripeFailures"
    }
    circuit_open = {
      pattern = "{ $.msg = \"circuit opened\" }"
      metric  = "ProviderCircuitOpen"
    }
  }
}

resource "aws_sns_topic" "p0_alerts" {
  name = local.monitoring_topic_name
}

data "aws_iam_policy_document" "p0_alerts" {
  statement {
    sid    = "AccountOwnerControl"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions = [
      "SNS:AddPermission",
      "SNS:DeleteTopic",
      "SNS:GetTopicAttributes",
      "SNS:ListSubscriptionsByTopic",
      "SNS:Publish",
      "SNS:RemovePermission",
      "SNS:SetTopicAttributes",
      "SNS:Subscribe",
    ]
    resources = [aws_sns_topic.p0_alerts.arn]
  }

  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.p0_alerts.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.apprunner_operation_failed.arn]
    }
  }

  statement {
    sid    = "AllowCloudWatchPublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.p0_alerts.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudwatch:${var.region}:${data.aws_caller_identity.current.account_id}:alarm:varsten-${var.environment}-*"]
    }
  }
}

resource "aws_sns_topic_policy" "p0_alerts" {
  arn    = aws_sns_topic.p0_alerts.arn
  policy = data.aws_iam_policy_document.p0_alerts.json
}

resource "aws_cloudwatch_event_rule" "apprunner_operation_failed" {
  name        = "varsten-${var.environment}-apprunner-operation-failed"
  description = "P0: App Runner deployment or service operation failed. Runbook: ${local.monitoring_runbook}"

  event_pattern = jsonencode({
    source      = ["aws.apprunner"]
    detail-type = ["AppRunner Service Operation Status Change"]
    detail = {
      serviceName = [aws_apprunner_service.api.service_name]
      operationStatus = [
        "CreateServiceFailed",
        "DeleteServiceFailed",
        "UpdateServiceFailed",
        "DeploymentFailed",
        "PauseServiceFailed",
        "ResumeServiceFailed",
      ]
    }
  })
}

resource "aws_cloudwatch_event_target" "apprunner_operation_failed" {
  rule      = aws_cloudwatch_event_rule.apprunner_operation_failed.name
  target_id = "p0-alerts"
  arn       = aws_sns_topic.p0_alerts.arn

  depends_on = [aws_sns_topic_policy.p0_alerts]
}

resource "aws_cloudwatch_metric_alarm" "apprunner_5xx" {
  alarm_name          = "varsten-${var.environment}-apprunner-5xx"
  alarm_description   = "P0: five or more 5xx responses in five minutes. Runbook: ${local.monitoring_runbook}"
  namespace           = "AWS/AppRunner"
  metric_name         = "5xxStatusResponses"
  dimensions          = local.app_dimensions
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "apprunner_latency" {
  alarm_name          = "varsten-${var.environment}-apprunner-latency-p95"
  alarm_description   = "P0: p95 request latency exceeded two seconds for three periods. Runbook: ${local.monitoring_runbook}"
  namespace           = "AWS/AppRunner"
  metric_name         = "RequestLatency"
  dimensions          = local.app_dimensions
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 2000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "apprunner_cpu" {
  alarm_name          = "varsten-${var.environment}-apprunner-cpu"
  alarm_description   = "P0: service CPU exceeded 85% for ten minutes. Runbook: ${local.monitoring_runbook}"
  namespace           = "AWS/AppRunner"
  metric_name         = "CPUUtilization"
  dimensions          = local.app_dimensions
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "apprunner_memory" {
  alarm_name          = "varsten-${var.environment}-apprunner-memory"
  alarm_description   = "P0: service memory exceeded 85% for ten minutes. Runbook: ${local.monitoring_runbook}"
  namespace           = "AWS/AppRunner"
  metric_name         = "MemoryUtilization"
  dimensions          = local.app_dimensions
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "application_failures" {
  for_each       = local.application_log_metrics
  name           = "varsten-${var.environment}-${replace(each.key, "_", "-")}"
  pattern        = each.value.pattern
  log_group_name = local.app_log_group

  metric_transformation {
    name      = each.value.metric
    namespace = "Varsten/${title(var.environment)}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "database_readiness" {
  alarm_name          = "varsten-${var.environment}-database-readiness"
  alarm_description   = "P0: repeated database readiness failures. Runbook: ${local.monitoring_runbook}"
  namespace           = "Varsten/${title(var.environment)}"
  metric_name         = "DatabaseReadinessFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_failures]
}

resource "aws_cloudwatch_metric_alarm" "scheduler" {
  alarm_name          = "varsten-${var.environment}-scheduler"
  alarm_description   = "P0: a background scheduler job failed. Runbook: ${local.monitoring_runbook}"
  namespace           = "Varsten/${title(var.environment)}"
  metric_name         = "SchedulerFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_failures]
}

resource "aws_cloudwatch_metric_alarm" "provider_key_vault" {
  alarm_name          = "varsten-${var.environment}-provider-key-vault"
  alarm_description   = "P0: a provider-key vault read/write/delete failed. Runbook: ${local.monitoring_runbook}"
  namespace           = "Varsten/${title(var.environment)}"
  metric_name         = "ProviderKeyVaultFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_failures]
}

resource "aws_cloudwatch_metric_alarm" "stripe" {
  alarm_name          = "varsten-${var.environment}-stripe"
  alarm_description   = "P0: Stripe checkout or portal integration failed. Runbook: ${local.monitoring_runbook}"
  namespace           = "Varsten/${title(var.environment)}"
  metric_name         = "StripeFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_failures]
}

resource "aws_cloudwatch_metric_alarm" "provider_circuit" {
  alarm_name          = "varsten-${var.environment}-provider-circuit"
  alarm_description   = "P0: provider circuits opened three times in five minutes. Runbook: ${local.monitoring_runbook}"
  namespace           = "Varsten/${title(var.environment)}"
  metric_name         = "ProviderCircuitOpen"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.p0_alerts.arn]
  ok_actions          = [aws_sns_topic.p0_alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_failures]
}
