"""HTTP load benchmark for the Varsten engine hot path.

This is the final pre-packaging capacity proof, distinct from
``scripts.benchmark_runner``:

- benchmark_runner proves savings math in-process;
- this script proves added HTTP latency and database behavior across a real
  backend process.

It starts a local mock OpenAI upstream, seeds a temporary Varsten project, starts
uvicorn on a local port with that project mapped to the mock provider key, and
drives four scenarios:

1. direct mock provider baseline
2. Varsten passthrough/cache-miss traffic
3. Varsten exact-cache hits
4. Varsten routed traffic

Run from ``backend/`` with the dev Postgres running:

    .venv/bin/python scripts/load_benchmark.py --target-rps 200 --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess  # nosec B404
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy import delete, select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import generate_api_key  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models import ApiKey, Organization, Project, ProxyCacheEntry, ProxyPolicy, UsageEvent  # noqa: E402
from app.proxy.cache import compute_cache_key  # noqa: E402
from scripts.seed_demo import _seed_prices  # noqa: E402

INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"
ORG_NAME = "load-benchmark-varsten"
PROJECT_NAME = "load-benchmark"


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """Fast local OpenAI-compatible mock upstream."""

    delay_ms = 3.0
    calls = 0
    lock = threading.Lock()

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?", 1)[0]
        if path.endswith("/embeddings"):
            return self._send(200, {"data": [{"embedding": [0.0] * 1536}], "usage": {"prompt_tokens": 1}})
        if path.endswith("/chat/completions"):
            with self.lock:
                type(self).calls += 1
            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000)
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
            prompt_chars = len(json.dumps(body.get("messages", []), default=str))
            in_tok = max(1, prompt_chars // 4)
            out_tok = 24
            model = body.get("model") or INCUMBENT
            return self._send(
                200,
                {
                    "id": f"chatcmpl-load-{time.time_ns()}",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "load benchmark response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": in_tok,
                        "completion_tokens": out_tok,
                        "total_tokens": in_tok + out_tok,
                    },
                },
            )
        return self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/__stats":
            return self._send(200, {"calls": type(self).calls})
        return self._send(200, {"ok": True})

    def log_message(self, *args) -> None:
        pass


@dataclass
class Workspace:
    org_id: uuid.UUID
    project_id: uuid.UUID
    api_key: str


@dataclass
class DbSnapshot:
    total_connections: int | None
    active_connections: int | None
    project_usage_events: int
    project_cache_entries: int


@dataclass
class ScenarioResult:
    name: str
    sent: int
    completed: int
    dropped: int
    errors: int
    non_2xx: int
    duration_s: float
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[int] = field(default_factory=Counter)
    headers: Counter[str] = field(default_factory=Counter)
    db_before: DbSnapshot | None = None
    db_after: DbSnapshot | None = None

    @property
    def achieved_rps(self) -> float:
        return self.completed / self.duration_s if self.duration_s > 0 else 0.0

    def percentile(self, p: float) -> float | None:
        if not self.latencies_ms:
            return None
        values = sorted(self.latencies_ms)
        idx = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
        return values[idx]


def seed_workspace() -> Workspace:
    session = get_session_factory()()
    try:
        org = session.scalar(select(Organization).where(Organization.name == ORG_NAME))
        if org is None:
            org = Organization(name=ORG_NAME, plan_tier="performance")
            session.add(org)
            session.flush()
        project = session.scalar(select(Project).where(Project.organization_id == org.id, Project.name == PROJECT_NAME))
        if project is None:
            project = Project(organization_id=org.id, name=PROJECT_NAME)
            session.add(project)
            session.flush()
        plaintext, prefix, key_hash = generate_api_key()
        session.add(ApiKey(project_id=project.id, name="load benchmark", key_prefix=prefix, key_hash=key_hash))
        _seed_prices(session)
        session.commit()
        return Workspace(org.id, project.id, plaintext)
    finally:
        session.close()


def cleanup_workspace(workspace: Workspace) -> None:
    session = get_session_factory()()
    try:
        session.execute(delete(Organization).where(Organization.id == workspace.org_id))
        session.commit()
    finally:
        session.close()


def clear_project_state(project_id: uuid.UUID) -> None:
    session = get_session_factory()()
    try:
        session.execute(delete(UsageEvent).where(UsageEvent.project_id == project_id))
        session.execute(delete(ProxyCacheEntry).where(ProxyCacheEntry.project_id == project_id))
        session.commit()
    finally:
        session.close()


def seed_repeated_cache_entry(project_id: uuid.UUID) -> None:
    body = payload_repeated(0)
    session = get_session_factory()()
    try:
        entry = ProxyCacheEntry(
            project_id=project_id,
            cache_key=compute_cache_key(body),
            model=INCUMBENT,
            response_payload={
                "id": "chatcmpl-load-cache-seed",
                "object": "chat.completion",
                "model": INCUMBENT,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "seeded cache response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
            input_tokens=20,
            output_tokens=5,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()


def set_routing_policy(workspace: Workspace, *, enabled: bool) -> None:
    session = get_session_factory()()
    try:
        project = session.get(Project, workspace.project_id)
        if project is None:
            raise RuntimeError("benchmark project missing")
        policy = session.scalar(
            select(ProxyPolicy).where(
                ProxyPolicy.project_id == project.id,
                ProxyPolicy.lever == "model_downshift",
                ProxyPolicy.target_key == INCUMBENT,
            )
        )
        if policy is None:
            policy = ProxyPolicy(
                organization_id=project.organization_id,
                project_id=project.id,
                lever="model_downshift",
                target_type="model",
                target_key=INCUMBENT,
            )
            session.add(policy)
        policy.enabled = enabled
        policy.holdback_percent = Decimal("0")
        policy.rollout_percent = 100
        policy.params = {"candidate_model": CANDIDATE}
        policy.activated_at = datetime.now(UTC)
        session.commit()
    finally:
        session.close()


def db_snapshot(project_id: uuid.UUID) -> DbSnapshot:
    session = get_session_factory()()
    try:
        total = active = None
        try:
            row = session.execute(
                text(
                    """
                    SELECT count(*)::int AS total,
                           count(*) FILTER (WHERE state = 'active')::int AS active
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    """
                )
            ).one()
            total = cast(int, row.total)
            active = cast(int, row.active)
        except Exception:
            session.rollback()
        usage_events = session.scalar(
            select(text("count(*)")).select_from(UsageEvent).where(UsageEvent.project_id == project_id)
        )
        cache_entries = session.scalar(
            select(text("count(*)")).select_from(ProxyCacheEntry).where(ProxyCacheEntry.project_id == project_id)
        )
        return DbSnapshot(total, active, int(usage_events or 0), int(cache_entries or 0))
    finally:
        session.close()


def wait_for(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # nosec B310
                if resp.status == 200:
                    return True
        except (OSError, TimeoutError, urllib.error.URLError):
            time.sleep(0.25)
            continue
        time.sleep(0.25)
    return False


def start_mock(port: int, delay_ms: float) -> ThreadingHTTPServer:
    MockOpenAIHandler.delay_ms = delay_ms
    MockOpenAIHandler.calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", port), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_backend(
    workspace: Workspace,
    *,
    backend_port: int,
    mock_port: int,
    workers: int,
    db_pool_size: int,
    db_max_overflow: int,
    detached_capture_concurrency: int,
) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "SCHEDULER_ENABLED": "false",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{mock_port}",
            "PROXY_OPENAI_KEYS": json.dumps({str(workspace.project_id): "sk-load-benchmark"}),
            "PROXY_RATE_LIMIT_PER_MINUTE": "1000000",
            "PROXY_CACHE_ENABLED": "true",
            "SEMANTIC_CACHE_ENABLED": "false",
            "PROXY_CAPTURE_DETACHED": "true",
            "API_KEY_POSITIVE_CACHE_ENABLED": "true",
            "PROXY_POLICY_CACHE_ENABLED": "true",
            "PROXY_POOL_MAX_CONNECTIONS": "1000",
            "PROXY_POOL_MAX_KEEPALIVE_CONNECTIONS": "500",
            "PROXY_CAPTURE_DETACHED_MAX_CONCURRENCY": str(detached_capture_concurrency),
            "DB_POOL_SIZE": str(db_pool_size),
            "DB_MAX_OVERFLOW": str(db_max_overflow),
        }
    )
    return subprocess.Popen(  # nosec B603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
            "--workers",
            str(workers),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def payload_unique(i: int) -> dict[str, Any]:
    return {
        "model": INCUMBENT,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": f"Load benchmark unique prompt {i}: summarize invoice state."},
        ],
        "stream": False,
    }


def payload_unique_warmup(i: int) -> dict[str, Any]:
    return payload_unique(i + 1_000_000)


def payload_repeated(_: int) -> dict[str, Any]:
    return {
        "model": INCUMBENT,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Load benchmark repeated prompt: summarize invoice state."},
        ],
        "stream": False,
    }


def route_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Varsten-Metadata": json.dumps(
            {"task_type": "classification.intent", "task_confidence": 0.98, "risk_level": "low"}
        ),
    }


async def run_load(
    *,
    name: str,
    url: str,
    headers: dict[str, str],
    payload_factory,
    target_rps: int,
    duration_s: float,
    concurrency: int,
    project_id: uuid.UUID,
) -> ScenarioResult:
    result = ScenarioResult(name=name, sent=0, completed=0, dropped=0, errors=0, non_2xx=0, duration_s=0.0)
    result.db_before = db_snapshot(project_id)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(10.0, connect=5.0)
    sem = asyncio.Semaphore(concurrency)
    start = time.perf_counter()
    end = start + duration_s
    tasks: set[asyncio.Task] = set()

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:

        async def one(idx: int) -> None:
            try:
                t0 = time.perf_counter()
                try:
                    resp = await client.post(url, headers=headers, json=payload_factory(idx))
                    elapsed = (time.perf_counter() - t0) * 1000
                    result.latencies_ms.append(elapsed)
                    result.statuses[resp.status_code] += 1
                    if resp.status_code // 100 != 2:
                        result.non_2xx += 1
                    else:
                        cache = resp.headers.get("x-varsten-cache")
                        arm = resp.headers.get("x-varsten-arm")
                        mode = resp.headers.get("x-varsten-mode")
                        routed = resp.headers.get("x-varsten-routed")
                        if cache:
                            result.headers[f"cache:{cache}"] += 1
                        if arm:
                            result.headers[f"arm:{arm}"] += 1
                        if mode:
                            result.headers[f"mode:{mode}"] += 1
                        if routed:
                            result.headers[f"routed:{routed}"] += 1
                    result.completed += 1
                except Exception:
                    result.errors += 1
            finally:
                sem.release()

        i = 0
        while time.perf_counter() < end:
            if sem.locked():
                result.dropped += 1
                i += 1
                next_at = start + (i / target_rps)
                sleep_for = next_at - time.perf_counter()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                continue
            await sem.acquire()
            task = asyncio.create_task(one(i))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            result.sent += 1
            i += 1
            next_at = start + (i / target_rps)
            sleep_for = next_at - time.perf_counter()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
        if tasks:
            await asyncio.gather(*tasks)

    result.duration_s = time.perf_counter() - start
    result.db_after = db_snapshot(project_id)
    return result


async def warmup(
    *,
    url: str,
    headers: dict[str, str],
    payload_factory,
    requests: int,
    concurrency: int,
) -> None:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(10.0, connect=5.0)) as client:

        async def one(idx: int) -> None:
            async with sem:
                with suppress(Exception):
                    await client.post(url, headers=headers, json=payload_factory(idx))

        await asyncio.gather(*(one(i) for i in range(requests)))


def _fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}ms"


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}ms"


def scenario_row(result: ScenarioResult, direct: ScenarioResult | None) -> str:
    p50 = result.percentile(0.50)
    p95 = result.percentile(0.95)
    p99 = result.percentile(0.99)
    direct_p99 = direct.percentile(0.99) if direct else None
    delta = (p99 - direct_p99) if p99 is not None and direct_p99 is not None else None
    return (
        f"| {result.name} | {result.sent} | {result.completed} | {result.dropped} | {result.achieved_rps:.0f} | "
        f"{_fmt_ms(p50)} | {_fmt_ms(p95)} | {_fmt_ms(p99)} | {_fmt_delta(delta)} | "
        f"{result.errors} | {result.non_2xx} |"
    )


def db_row(result: ScenarioResult) -> str:
    before = result.db_before or DbSnapshot(None, None, 0, 0)
    after = result.db_after or DbSnapshot(None, None, 0, 0)
    before_conn = "-" if before.total_connections is None else str(before.total_connections)
    after_conn = "-" if after.total_connections is None else str(after.total_connections)
    before_active = "-" if before.active_connections is None else str(before.active_connections)
    after_active = "-" if after.active_connections is None else str(after.active_connections)
    return (
        f"| {result.name} | {before_conn} | {after_conn} | {before_active} | {after_active} | "
        f"{before.project_usage_events} | {after.project_usage_events} | "
        f"{before.project_cache_entries} | {after.project_cache_entries} |"
    )


def write_report(
    path: Path,
    results: list[ScenarioResult],
    *,
    target_rps: int,
    duration_s: float,
    db_pool_size: int,
    db_max_overflow: int,
    workers: int,
    detached_capture: bool,
    detached_capture_concurrency: int,
) -> None:
    direct = next((r for r in results if r.name == "direct_mock_provider"), None)
    passthrough = next((r for r in results if r.name == "varsten_passthrough"), None)
    passthrough_delta = None
    if direct and passthrough and direct.percentile(0.99) is not None and passthrough.percentile(0.99) is not None:
        passthrough_delta = cast(float, passthrough.percentile(0.99)) - cast(float, direct.percentile(0.99))
    gate_pass = (
        passthrough is not None
        and passthrough.errors == 0
        and passthrough.non_2xx == 0
        and passthrough_delta is not None
        and passthrough_delta <= 9.0
    )
    lines = [
        "# Engine Load Benchmark",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "This benchmark drives a real local Varsten HTTP process against a local",
        "OpenAI-compatible mock provider. It spends no provider tokens.",
        "",
        f"- Target RPS: `{target_rps}`",
        f"- Scenario duration: `{duration_s:.1f}s`",
        f"- Backend workers: `{workers}`",
        f"- Backend DB pool: `pool_size={db_pool_size}`, `max_overflow={db_max_overflow}`",
        f"- Detached capture: `{'enabled' if detached_capture else 'disabled'}` "
        f"(`max_concurrency={detached_capture_concurrency}`)",
        "- Passthrough p99 gate: `<= +9.0ms` vs direct mock provider",
        f"- Gate result: `{'PASS' if gate_pass else 'FAIL'}`",
        "",
        "## Latency",
        "",
        "| Scenario | Sent | Completed | Dropped | Achieved RPS | p50 | p95 | p99 | Added p99 vs direct | Errors | Non-2xx |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(scenario_row(r, direct) for r in results)
    lines.extend(
        [
            "",
            "## DB Behavior",
            "",
            "| Scenario | DB conns before | DB conns after | Active before | Active after | Usage before | Usage after | Cache before | Cache after |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(db_row(r) for r in results)
    lines.extend(["", "## Header Counts", ""])
    for result in results:
        lines.append(f"### {result.name}")
        if result.headers:
            for key, count in sorted(result.headers.items()):
                lines.append(f"- `{key}`: {count}")
        else:
            lines.append("- No Varsten headers recorded.")
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "- `direct_mock_provider` is the local upstream baseline.",
            "- `varsten_passthrough` exercises auth, planning, ledger writes, and upstream forwarding without an active optimization policy.",
            "- `varsten_cache_hit` exercises the exact-cache hot path after one priming request.",
            "- `varsten_routed` exercises model-routing policy lookup, treatment assignment, ledger proof, and upstream forwarding.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


async def run(args: argparse.Namespace, workspace: Workspace, api_url: str, mock_url: str) -> list[ScenarioResult]:
    clear_project_state(workspace.project_id)
    set_routing_policy(workspace, enabled=False)
    await warmup(
        url=f"{mock_url}/v1/chat/completions",
        headers={"Authorization": "Bearer sk-load-benchmark"},
        payload_factory=payload_unique_warmup,
        requests=args.warmup_requests,
        concurrency=min(args.concurrency, args.warmup_requests),
    )
    direct = await run_load(
        name="direct_mock_provider",
        url=f"{mock_url}/v1/chat/completions",
        headers={"Authorization": "Bearer sk-load-benchmark"},
        payload_factory=payload_unique,
        target_rps=args.target_rps,
        duration_s=args.duration,
        concurrency=args.concurrency,
        project_id=workspace.project_id,
    )

    clear_project_state(workspace.project_id)
    set_routing_policy(workspace, enabled=False)
    await warmup(
        url=f"{api_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {workspace.api_key}"},
        payload_factory=payload_unique_warmup,
        requests=args.warmup_requests,
        concurrency=min(args.concurrency, args.warmup_requests),
    )
    await asyncio.sleep(args.capture_drain_seconds)
    clear_project_state(workspace.project_id)
    passthrough = await run_load(
        name="varsten_passthrough",
        url=f"{api_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {workspace.api_key}"},
        payload_factory=payload_unique,
        target_rps=args.target_rps,
        duration_s=args.duration,
        concurrency=args.concurrency,
        project_id=workspace.project_id,
    )

    clear_project_state(workspace.project_id)
    set_routing_policy(workspace, enabled=False)
    seed_repeated_cache_entry(workspace.project_id)
    cache_hit = await run_load(
        name="varsten_cache_hit",
        url=f"{api_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {workspace.api_key}"},
        payload_factory=payload_repeated,
        target_rps=args.target_rps,
        duration_s=args.duration,
        concurrency=args.concurrency,
        project_id=workspace.project_id,
    )

    clear_project_state(workspace.project_id)
    set_routing_policy(workspace, enabled=True)
    await warmup(
        url=f"{api_url}/v1/chat/completions",
        headers=route_headers(workspace.api_key),
        payload_factory=payload_unique_warmup,
        requests=args.warmup_requests,
        concurrency=min(args.concurrency, args.warmup_requests),
    )
    await asyncio.sleep(args.capture_drain_seconds)
    clear_project_state(workspace.project_id)
    routed = await run_load(
        name="varsten_routed",
        url=f"{api_url}/v1/chat/completions",
        headers=route_headers(workspace.api_key),
        payload_factory=payload_unique,
        target_rps=args.target_rps,
        duration_s=args.duration,
        concurrency=args.concurrency,
        project_id=workspace.project_id,
    )
    return [direct, passthrough, cache_hit, routed]


def main() -> int:
    parser = argparse.ArgumentParser(description="Varsten HTTP load benchmark")
    parser.add_argument("--target-rps", type=int, default=200)
    parser.add_argument("--duration", type=float, default=15.0, help="Seconds per scenario")
    parser.add_argument("--concurrency", type=int, default=250)
    parser.add_argument("--backend-port", type=int, default=8097)
    parser.add_argument("--mock-port", type=int, default=8096)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--mock-delay-ms", type=float, default=3.0)
    parser.add_argument("--warmup-requests", type=int, default=50)
    parser.add_argument("--capture-drain-seconds", type=float, default=2.0)
    parser.add_argument("--db-pool-size", type=int, default=50)
    parser.add_argument("--db-max-overflow", type=int, default=50)
    parser.add_argument("--detached-capture-concurrency", type=int, default=4)
    parser.add_argument("--report", default=str(REPO_ROOT / "docs" / "ENGINE_LOAD_BENCHMARK.md"))
    parser.add_argument("--keep", action="store_true", help="Keep seeded benchmark org/project rows")
    args = parser.parse_args()

    workspace = seed_workspace()
    mock = start_mock(args.mock_port, args.mock_delay_ms)
    backend = start_backend(
        workspace,
        backend_port=args.backend_port,
        mock_port=args.mock_port,
        workers=args.workers,
        db_pool_size=args.db_pool_size,
        db_max_overflow=args.db_max_overflow,
        detached_capture_concurrency=args.detached_capture_concurrency,
    )
    api_url = f"http://127.0.0.1:{args.backend_port}"
    mock_url = f"http://127.0.0.1:{args.mock_port}"
    try:
        if not wait_for(f"{api_url}/health/ready", timeout=40):
            print("ERROR: backend did not become ready", file=sys.stderr)
            return 1
        results = asyncio.run(run(args, workspace, api_url, mock_url))
        report_path = Path(args.report)
        write_report(
            report_path,
            results,
            target_rps=args.target_rps,
            duration_s=args.duration,
            workers=args.workers,
            db_pool_size=args.db_pool_size,
            db_max_overflow=args.db_max_overflow,
            detached_capture=True,
            detached_capture_concurrency=args.detached_capture_concurrency,
        )
        print(f"Wrote {report_path}")
        for result in results:
            print(
                f"{result.name}: sent={result.sent} completed={result.completed} "
                f"dropped={result.dropped} rps={result.achieved_rps:.0f} p99={_fmt_ms(result.percentile(0.99))} "
                f"errors={result.errors} non_2xx={result.non_2xx}"
            )
        return 0
    finally:
        backend.send_signal(signal.SIGTERM)
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
        mock.shutdown()
        if not args.keep:
            cleanup_workspace(workspace)


if __name__ == "__main__":
    raise SystemExit(main())
