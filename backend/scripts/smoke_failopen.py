r"""End-to-end fail-open smoke test.

Stands up the real stack and drives the real SDK across process boundaries:

    Node SDK (@varsten/openai)  ->  real Varsten backend (uvicorn)  ->  mock provider
                          \-------- direct fallback --------/

It seeds a project + vk_ key in the dev database, points the proxy's upstream and
the SDK's direct-fallback target at an in-process mock provider, runs the SDK
scenarios (optimized, provider-error relay, health, telemetry, backend-down
fallback, circuit-open fallback), then asserts the backend ledger recorded the
optimized call. Everything is torn down and the seeded rows are deleted.

Run from the backend directory:

    .venv/bin/python scripts/smoke_failopen.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SDK_DIR = REPO_ROOT / "sdk" / "openai"

# Allow `import app...` when run as a plain script (pytest adds this automatically).
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BACKEND_PORT = 8099
MOCK_PORT = 8098

CANNED_COMPLETION = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from the mock provider"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
}

# Mutable mock state, flipped by the SDK via POST /__mode.
MOCK_STATE: dict[str, object] = {"mode": "ok", "calls": 0}


class MockProviderHandler(BaseHTTPRequestHandler):
    """A stand-in OpenAI upstream. Serves both the proxy's upstream calls and the
    SDK's direct-fallback calls, and exposes a control endpoint to flip behaviour."""

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]

        if path == "/__mode":
            try:
                mode = json.loads(raw or b"{}").get("mode", "ok")
            except Exception:
                mode = "ok"
            MOCK_STATE["mode"] = mode
            return self._send(200, {"ok": True, "mode": mode})

        if path.endswith("/embeddings"):
            return self._send(200, {"data": [{"embedding": [0.0] * 1536}]})

        if path.endswith("/chat/completions"):
            MOCK_STATE["calls"] = cast(int, MOCK_STATE["calls"]) + 1
            mode = MOCK_STATE["mode"]
            if mode == "fail_400":
                return self._send(400, {"error": {"message": "bad request", "type": "invalid_request_error"}})
            if mode == "fail_500":
                return self._send(500, {"error": {"message": "server error", "type": "server_error"}})
            return self._send(200, CANNED_COMPLETION)

        return self._send(404, {"error": "not found"})

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/__stats":
            return self._send(200, dict(MOCK_STATE))
        return self._send(200, {"ok": True})

    def log_message(self, *args) -> None:  # silence access logs
        pass


def seed_project() -> tuple[str, str, str]:
    """Create an org + project + API key directly. Returns (org_id, project_id, vk_)."""
    from app.core.security import generate_api_key
    from app.db.session import get_session_factory
    from app.models import ApiKey, Organization, Project

    session = get_session_factory()()
    try:
        org = Organization(name="smoke-failopen-org", plan_tier="performance")
        session.add(org)
        session.flush()
        project = Project(organization_id=org.id, name="smoke")
        session.add(project)
        session.flush()
        plaintext, prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, name="smoke", key_prefix=prefix, key_hash=key_hash)
        session.add(api_key)
        session.commit()
        return str(org.id), str(project.id), plaintext
    finally:
        session.close()


def delete_org(org_id: str) -> None:
    from sqlalchemy import text

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org_id})
        session.commit()
    except Exception as exc:  # best-effort cleanup
        session.rollback()
        print(f"[smoke] cleanup warning: {exc}")
    finally:
        session.close()


def ledger_has_optimized_miss(project_id: str) -> bool:
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models import UsageEvent

    session = get_session_factory()()
    try:
        events = session.scalars(select(UsageEvent).where(UsageEvent.project_id == uuid.UUID(project_id))).all()
        return any((e.event_metadata or {}).get("cache") == "miss" for e in events)
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
            time.sleep(0.4)
            continue
        time.sleep(0.4)
    return False


def build_sdk() -> None:
    print("[smoke] building SDK...")
    subprocess.run(  # nosec B603 B607
        ["npm", "run", "build"], cwd=str(SDK_DIR), check=True, capture_output=True, text=True
    )


def run_local() -> int:
    os.chdir(BACKEND_DIR)
    build_sdk()

    org_id, project_id, vk_key = seed_project()
    print(f"[smoke] seeded project {project_id}")

    httpd = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockProviderHandler)
    mock_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    mock_thread.start()
    print(f"[smoke] mock provider on :{MOCK_PORT}")

    backend_env = os.environ.copy()
    backend_env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}"
    backend_env["PROXY_OPENAI_KEYS"] = json.dumps({project_id: "sk-mock"})
    backend_env["APP_ENV"] = "development"
    backend_env["SCHEDULER_ENABLED"] = "false"
    backend_env["SEMANTIC_CACHE_ENABLED"] = "false"

    backend = subprocess.Popen(  # nosec B603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BACKEND_PORT), "--log-level", "warning"],
        cwd=str(BACKEND_DIR),
        env=backend_env,
    )

    node_ok = False
    ledger_ok = False
    try:
        if not wait_for(f"http://127.0.0.1:{BACKEND_PORT}/v1/health"):
            print("[smoke] backend did not become healthy")
            return 1
        print("[smoke] backend healthy; running SDK scenarios\n")

        node_env = os.environ.copy()
        node_env.update(
            {
                "VARSTEN_API_KEY": vk_key,
                "OPENAI_API_KEY": "sk-mock",
                "VARSTEN_BASE_URL": f"http://127.0.0.1:{BACKEND_PORT}/v1",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
                "MOCK_URL": f"http://127.0.0.1:{MOCK_PORT}",
                "BACKEND_DOWN_URL": "http://127.0.0.1:1/v1",
            }
        )
        result = subprocess.run(  # nosec B603 B607
            ["node", "smoke/run.mjs"], cwd=str(SDK_DIR), env=node_env, capture_output=True, text=True
        )
        print(result.stdout, end="")
        if result.stderr.strip():
            print("[node stderr]\n" + result.stderr)
        node_ok = result.returncode == 0

        ledger_ok = ledger_has_optimized_miss(project_id)
        print(f"\n[smoke] ledger recorded optimized miss: {ledger_ok}")
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
        httpd.shutdown()
        delete_org(org_id)
        print("[smoke] torn down")

    passed = node_ok and ledger_ok
    print(
        f"\n[smoke] RESULT: {'PASS' if passed else 'FAIL'} "
        f"(sdk_scenarios={'ok' if node_ok else 'fail'}, ledger={'ok' if ledger_ok else 'fail'})"
    )
    return 0 if passed else 1


def run_remote(base_url: str) -> int:
    """Drive the SDK against a DEPLOYED Varsten over the real network.

    No local backend or DB: only a local mock provider for the fallback leg. The
    Varsten leg crosses the real internet. Credential-free checks (remote health,
    unreachable -> fallback) always run; the contract checks run when
    VARSTEN_SMOKE_KEY (a vk_ for a project on the deployed instance) is set.
    """
    os.chdir(BACKEND_DIR)
    build_sdk()

    base_url = base_url.rstrip("/")
    httpd = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockProviderHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[smoke] mock provider (fallback target) on :{MOCK_PORT}")
    print(f"[smoke] target Varsten: {base_url}\n")

    node_env = os.environ.copy()
    node_env.update(
        {
            "VARSTEN_BASE_URL": base_url,
            # A non-resolving host so the Varsten leg fails DNS for real.
            "DEAD_URL": "https://varsten-staging-unreachable.invalid/v1",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
            "MOCK_URL": f"http://127.0.0.1:{MOCK_PORT}",
            "VARSTEN_SMOKE_KEY": os.environ.get("VARSTEN_SMOKE_KEY", ""),
        }
    )
    try:
        result = subprocess.run(  # nosec B603 B607
            ["node", "smoke/run-remote.mjs"], cwd=str(SDK_DIR), env=node_env, capture_output=True, text=True
        )
        print(result.stdout, end="")
        if result.stderr.strip():
            print("[node stderr]\n" + result.stderr)
    finally:
        httpd.shutdown()

    ok = result.returncode == 0
    print(f"\n[smoke] REMOTE RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-open smoke test (local or against a deployed Varsten).")
    parser.add_argument(
        "--remote",
        metavar="BASE_URL",
        help="Run against a deployed Varsten (e.g. https://host/v1) instead of a local backend.",
    )
    args = parser.parse_args()
    if args.remote:
        return run_remote(args.remote)
    return run_local()


if __name__ == "__main__":
    raise SystemExit(main())
