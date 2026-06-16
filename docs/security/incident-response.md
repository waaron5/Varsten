# Incident Response Runbook

Internal runbook for security and availability incidents. Varsten sits inline in a
customer's request path, so the first move in almost every incident is the same:
stop optimizing, keep traffic flowing.

## Severity

- **SEV1** — customer traffic failing or at risk (proxy down, DB unreachable,
  suspected key compromise, cross-tenant exposure).
- **SEV2** — degraded but serving (elevated latency, a lever misbehaving, partial
  provider outage).
- **SEV3** — internal-only or cosmetic (dashboard bug, delayed background job).

## First move: fail open

Varsten is built to fail open — if the control plane, cache, or plan lookup is
unreachable, requests forward straight to the upstream provider, still metered.
If anything in the optimization path is suspect, make that explicit:

- **Global kill switch:** set `PROXY_KILL_SWITCH=true` and redeploy/restart. Every
  project's traffic bypasses all optimization and forwards to the provider.
- **Single project:** flip that project's `proxy_bypass_enabled`. Same effect,
  scoped to one tenant.

Savings stop; traffic does not. This is the correct response to almost any inline
incident while you investigate.

## Playbooks

### Suspected provider-key compromise
1. Rotate the key at the provider.
2. Reconnect the new key through the dashboard Connections flow (writes to Secrets
   Manager, validated before store). The disconnect + reconnect are in the audit
   log.
3. Review the audit log (`/v1/admin/audit-log`) for unexpected `provider_key.*`
   events and the access logs for unexpected source IPs.

### Suspected cross-tenant exposure (SEV1, highest priority)
1. Capture evidence: request IDs, the two tenants, the offending response.
2. Kill switch on while you confirm.
3. Tenant isolation runs through `_assert_member` and project-scoped queries;
   review the specific endpoint's authorization path against the tenancy model.
4. If confirmed, notify affected customers per the DPA timeline.

### Database unreachable (SEV1)
1. `/health/ready` will be failing; the app stays live but cannot serve reads.
2. The proxy still fails open for forwarding where it can.
3. Restore path: see `OPERATIONS_DEPLOY.md` (PITR restore drill). Use the measured
   RTO/RPO from the last drill to set expectations.

### A lever degrades quality in production (SEV2)
1. The live drift guard auto-rolls-back a routed/trimmed arm that degrades against
   its concurrent control (objective signal only).
2. If it has not, disable the lever or kill-switch the project.
3. Confirm the rollback in the decision queue.

### Proxy bug / bad deploy (SEV1/2)
1. Roll back to the previous image tag (`terraform apply -var image_tag=<prev SHA>`;
   ECR tags are immutable, so the prior image is exactly what ran).
2. Kill switch if the rollback is not immediate.

## Communication

- Internal: declare severity, owner, and a status channel.
- Customer: for SEV1 affecting a customer, notify per the DPA. Lead with impact and
  the mitigation already in place (usually "traffic is flowing; optimization is
  paused").

## After action

Every SEV1/SEV2 gets a written post-incident review: timeline, root cause,
customer impact, and the concrete follow-ups (with owners). File the follow-ups as
tracked work, not intentions.

## Artifacts a serious reviewer will ask for

SOC 2 Type II report (under NDA), DPA, subprocessor list, pen test summary, and a
data flow diagram. Status of each is tracked in the security plan; do not claim an
artifact exists before it does.
