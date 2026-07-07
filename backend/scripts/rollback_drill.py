"""Optimization rollback drill.

Runs a real local backend against a mock provider and proves the per-project
bypass switch immediately returns traffic to pass-through behavior, then restores
optimization.

Run from ``backend/``:

    .venv/bin/python scripts/rollback_drill.py
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess  # nosec B404
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import get_session_factory  # noqa: E402
from app.models import Project  # noqa: E402
from scripts.load_benchmark import (  # noqa: E402
    cleanup_workspace,
    payload_unique,
    route_headers,
    seed_workspace,
    set_routing_policy,
    start_backend,
    start_mock,
    wait_for,
)


def set_project_bypass(project_id: uuid.UUID, enabled: bool) -> None:
    session = get_session_factory()()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise RuntimeError(f"project not found: {project_id}")
        project.proxy_bypass_enabled = enabled
        session.commit()
    finally:
        session.close()


async def call(api_url: str, api_key: str, idx: int) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10) as client:
        return await client.post(
            f"{api_url}/v1/chat/completions",
            headers=route_headers(api_key),
            json=payload_unique(idx),
        )


def check_response(label: str, response: httpx.Response, *, expect_bypass: bool) -> dict:
    mode = response.headers.get("x-varsten-mode")
    cache = response.headers.get("x-varsten-cache")
    routed = response.headers.get("x-varsten-routed")
    ok = response.status_code == 200
    if expect_bypass:
        ok = ok and mode == "bypass" and cache == "bypass" and routed is None
    else:
        ok = ok and mode == "optimize" and routed is not None
    return {
        "label": label,
        "ok": ok,
        "status": response.status_code,
        "x_varsten_mode": mode,
        "x_varsten_cache": cache,
        "x_varsten_routed": routed,
    }


async def run_drill(args: argparse.Namespace) -> list[dict]:
    workspace = seed_workspace()
    set_routing_policy(workspace, enabled=True)
    mock = start_mock(args.mock_port, args.mock_delay_ms)
    backend = start_backend(
        workspace,
        backend_port=args.backend_port,
        mock_port=args.mock_port,
        workers=1,
        db_pool_size=10,
        db_max_overflow=10,
        detached_capture_concurrency=2,
    )
    api_url = f"http://127.0.0.1:{args.backend_port}"
    try:
        if not wait_for(f"{api_url}/health/ready", timeout=40):
            raise RuntimeError("backend did not become ready")
        before = await call(api_url, workspace.api_key, 1)
        set_project_bypass(workspace.project_id, True)
        bypassed = await call(api_url, workspace.api_key, 2)
        set_project_bypass(workspace.project_id, False)
        restored = await call(api_url, workspace.api_key, 3)
        return [
            check_response("optimization_before_bypass", before, expect_bypass=False),
            check_response("project_bypass_enabled", bypassed, expect_bypass=True),
            check_response("optimization_restored", restored, expect_bypass=False),
        ]
    finally:
        backend.send_signal(signal.SIGTERM)
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
        mock.shutdown()
        if not args.keep:
            cleanup_workspace(workspace)


def write_report(path: Path, results: list[dict]) -> None:
    passed = all(r["ok"] for r in results)
    lines = [
        "# Engine Rollback Drill",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"Result: `{'PASS' if passed else 'FAIL'}`",
        "",
        "| Step | OK | HTTP | X-Varsten-Mode | X-Varsten-Cache | X-Varsten-Routed |",
        "|---|---:|---:|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result['label']} | {result['ok']} | {result['status']} | "
            f"{result['x_varsten_mode'] or '-'} | {result['x_varsten_cache'] or '-'} | "
            f"{result['x_varsten_routed'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "This drill used the per-project bypass flag. It proves the operational",
            "rollback lever can stop optimization without changing application code or",
            "provider credentials, and can restore optimization after the flag is cleared.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Varsten optimization rollback drill")
    parser.add_argument("--backend-port", type=int, default=8095)
    parser.add_argument("--mock-port", type=int, default=8094)
    parser.add_argument("--mock-delay-ms", type=float, default=3.0)
    parser.add_argument("--report", default=str(REPO_ROOT / "docs" / "ENGINE_ROLLBACK_DRILL.md"))
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    import asyncio

    results = asyncio.run(run_drill(args))
    report_path = Path(args.report)
    write_report(report_path, results)
    print(f"Wrote {report_path}")
    print(json.dumps(results, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
