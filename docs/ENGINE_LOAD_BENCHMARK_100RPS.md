# Engine Load Benchmark

Generated: 2026-07-06T14:42:33.229099+00:00

This benchmark drives a real local Varsten HTTP process against a local
OpenAI-compatible mock provider. It spends no provider tokens.

- Target RPS: `100`
- Scenario duration: `10.0s`
- Backend workers: `8`
- Backend DB pool: `pool_size=5`, `max_overflow=5`
- Detached capture: `enabled` (`max_concurrency=1`)
- Passthrough p99 gate: `<= +9.0ms` vs direct mock provider
- Gate result: `FAIL`

## Latency

| Scenario | Sent | Completed | Dropped | Achieved RPS | p50 | p95 | p99 | Added p99 vs direct | Errors | Non-2xx |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 1000 | 1000 | 0 | 100 | 7.8ms | 9.0ms | 16.6ms | +0.0ms | 0 | 0 |
| varsten_passthrough | 1000 | 1000 | 0 | 97 | 29.7ms | 193.6ms | 413.6ms | +397.0ms | 0 | 0 |
| varsten_cache_hit | 1000 | 1000 | 0 | 100 | 4.4ms | 6.7ms | 11.1ms | -5.5ms | 0 | 0 |
| varsten_routed | 1000 | 1000 | 0 | 100 | 20.7ms | 40.5ms | 70.4ms | +53.8ms | 0 | 0 |

## DB Behavior

| Scenario | DB conns before | DB conns after | Active before | Active after | Usage before | Usage after | Cache before | Cache after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| direct_mock_provider | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
| varsten_passthrough | 27 | 27 | 1 | 1 | 0 | 998 | 0 | 996 |
| varsten_cache_hit | 27 | 27 | 1 | 1 | 1 | 495 | 1 | 1 |
| varsten_routed | 29 | 29 | 1 | 1 | 0 | 627 | 0 | 627 |

## Header Counts

### direct_mock_provider
- No Varsten headers recorded.

### varsten_passthrough
- `cache:miss`: 1000
- `mode:optimize`: 1000

### varsten_cache_hit
- `cache:hit`: 1000
- `mode:optimize`: 1000

### varsten_routed
- `arm:treatment`: 506
- `cache:hit`: 295
- `cache:miss`: 705
- `mode:optimize`: 1000
- `routed:gpt-4o->gpt-4o-mini`: 506

## Interpretation

- `direct_mock_provider` is the local upstream baseline.
- `varsten_passthrough` exercises auth, planning, ledger writes, and upstream forwarding without an active optimization policy.
- `varsten_cache_hit` exercises the exact-cache hot path after one priming request.
- `varsten_routed` exercises model-routing policy lookup, treatment assignment, ledger proof, and upstream forwarding.

## Conclusion

This diagnostic shows the current local envelope after the hot-path capacity
edits. Varsten completed 100 RPS without drops, and cache hits met the latency
bar, but passthrough and routed traffic still missed the single-digit added-p99
target. This does not replace the failed 200 RPS gate.
