# Production alert runbook

Every production P0 alert routes through the `varsten-production-p0-alerts` SNS
topic. The founder owns acknowledgment until a formal on-call rotation exists.
Never paste credentials, provider keys, request bodies, prompts, or customer data
into an incident ticket or chat.

The SNS topic, policies, alarms, and EventBridge target are managed by Terraform.
Email subscriptions are created and confirmed directly in SNS because the AWS
Terraform provider classifies the email protocol as partially supported: its
confirmation occurs outside Terraform. Record and drill every human destination.

## First response

1. Record the alert name, UTC time, service, and AWS request or event identifier.
2. Check `https://api.varsten.ai/health/ready` and the App Runner service status.
3. Check Sentry and the App Runner application/service logs for the same window.
4. If customer traffic is at risk, enable the project bypass or global
   `PROXY_KILL_SWITCH` so optimization fails open to the configured provider.
5. Do not rotate, retrieve, or expose customer provider keys while diagnosing.
6. Record containment, recovery time, and whether customer notification review is
   required under the incident-response policy.

## Alarm actions

| Alarm | Immediate investigation | Containment |
| --- | --- | --- |
| `apprunner-operation-failed` | App Runner event and deployment/service logs | Keep the last healthy revision serving; redeploy the prior immutable image if needed |
| `apprunner-5xx` | Status distribution, Sentry, application logs, recent deploy | Roll back a bad deploy; enable bypass when optimization is implicated |
| `apprunner-latency-p95` | Concurrency, CPU/memory, database latency, provider latency | Bypass optimization; cap traffic or scale only within verified DB limits |
| `apprunner-cpu` / `apprunner-memory` | Instance count, concurrency, recent workload | Reduce nonessential jobs; scale only within connection-pool capacity |
| `database-readiness` | Neon status, connection errors, pool use, credential changes | Stop data-changing operations; follow the Neon recovery runbook if data integrity is in doubt |
| `scheduler` | Failed job name and traceback | Disable only the failing noncritical job; never run duplicate destructive sweeps |
| `provider-key-vault` | KMS, Secrets Manager, IAM, and CloudTrail events | Pause new key onboarding; do not export plaintext keys |
| `stripe` | Stripe request/event ID, signature and webhook configuration | Disable self-serve billing; preserve current entitlements for manual review |
| `provider-circuit` | Provider/status/model distribution and upstream status | Bypass optimization or affected routes; do not retry without bounds |

## Resolution

Keep the incident open until readiness is healthy, the alarm returns to `OK`, and
a customer-like request succeeds safely. Record the root cause and a follow-up
owner. Treat an `OK` notification as evidence of metric recovery, not proof that
the underlying incident is fully resolved.

## Known Phase 6 gaps

- The first production SNS email subscription was deleted during setup. Although
  AWS accepted the Phase 6.4 direct, `ALARM`, and `OK` publications, none reached
  the founder; that drill failed. A replacement subscription must be confirmed
  and the drill repeated before delivery is considered operational.
- External uptime monitoring and its phone/email delivery are configured outside
  AWS and require a human-operated account.
- Sentry alert rules, release tracking, source maps, and server-side scrubbing
  require Sentry account access and an end-to-end delivery test.
- Authentication-rate and request-disappearance alarms require a stable customer
  traffic baseline or independent synthetic heartbeat to avoid false positives.
- Pricing coverage and excessive unpriced-event alarms require durable custom
  application metrics; they are not inferred from log text.
