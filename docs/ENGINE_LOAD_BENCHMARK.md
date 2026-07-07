# Engine Load Benchmark

Generated: 2026-07-06T14:44:03.538020+00:00

This benchmark drives a real local Varsten HTTP process against a local
OpenAI-compatible mock provider. It spends no provider tokens.

- Target RPS: `200`
- Scenario duration: `10.0s`
- Backend workers: `8`
- Backend DB pool: `pool_size=5`, `max_overflow=5`
- Detached capture: `enabled` (`max_concurrency=1`)
- Passthrough p99 gate: `<= +9.0ms` vs direct mock provider
- Gate result: `FAIL`

## Latency

| Scenario | Sent | Completed | Dropped | Achieved RPS | p50 | p95 | p99 | Added p99 vs direct | Errors | Non-2xx |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 2000 | 2000 | 0 | 200 | 9.0ms | 20.8ms | 81.2ms | +0.0ms | 0 | 0 |
| varsten_passthrough | 925 | 925 | 1074 | 66 | 2184.7ms | 8306.8ms | 11125.4ms | +11044.1ms | 0 | 0 |
| varsten_cache_hit | 1075 | 1075 | 915 | 89 | 1510.9ms | 6711.6ms | 8591.3ms | +8510.0ms | 0 | 0 |
| varsten_routed | 1046 | 1046 | 951 | 82 | 1823.9ms | 7108.7ms | 9559.9ms | +9478.7ms | 0 | 0 |

## DB Behavior

| Scenario | DB conns before | DB conns after | Active before | Active after | Usage before | Usage after | Cache before | Cache after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
| varsten_passthrough | 29 | 31 | 1 | 1 | 0 | 920 | 0 | 920 |
| varsten_cache_hit | 31 | 31 | 1 | 2 | 3 | 1067 | 1 | 1 |
| varsten_routed | 31 | 31 | 1 | 1 | 0 | 987 | 0 | 986 |

## Header Counts

### direct_mock_provider
- No Varsten headers recorded.

### varsten_passthrough
- `cache:miss`: 925
- `mode:optimize`: 925

### varsten_cache_hit
- `cache:hit`: 1075
- `mode:optimize`: 1075

### varsten_routed
- `arm:treatment`: 995
- `cache:hit`: 51
- `cache:miss`: 995
- `mode:optimize`: 1046
- `routed:gpt-4o->gpt-4o-mini`: 995

## Interpretation

- `direct_mock_provider` is the local upstream baseline.
- `varsten_passthrough` exercises auth, planning, ledger writes, and upstream forwarding without an active optimization policy.
- `varsten_cache_hit` exercises the exact-cache hot path after one priming request.
- `varsten_routed` exercises model-routing policy lookup, treatment assignment, ledger proof, and upstream forwarding.

## Conclusion

This is not a release pass. The local direct provider baseline sustained 200 RPS,
but Varsten did not: scheduled sends were dropped and p99 latency rose into
seconds. Redis and rollback are no longer blockers; remaining engine work is
hot-path capacity.
