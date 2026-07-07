# Engine Rollback Drill

Generated: 2026-07-05T23:35:21.576603+00:00

Result: `PASS`

| Step | OK | HTTP | X-Varsten-Mode | X-Varsten-Cache | X-Varsten-Routed |
|---|---:|---:|---|---|---|
| optimization_before_bypass | True | 200 | optimize | miss | gpt-4o->gpt-4o-mini |
| project_bypass_enabled | True | 200 | bypass | bypass | - |
| optimization_restored | True | 200 | optimize | miss | gpt-4o->gpt-4o-mini |

This drill used the per-project bypass flag. It proves the operational
rollback lever can stop optimization without changing application code or
provider credentials, and can restore optimization after the flag is cleared.
