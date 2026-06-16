"""Batching lever: the async /v1/batches data plane.

Covers the storage interface, the full lifecycle (stage input -> upload -> submit
-> poll -> finalize), the measured batch-vs-sync savings, the ledger write, and
tenant isolation. OpenAI's Batch/Files API is mocked via httpx MockTransport; the
local filesystem storage backend stands in for S3.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import BatchJob, ModelPrice, Organization, Project, UsageEvent
from app.proxy import openai_batch
from app.storage import LocalStorage

MODEL = "gpt-4o-mini"


@pytest.fixture(autouse=True)
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "batch_storage_backend", "local")
    monkeypatch.setattr(settings, "batch_local_storage_dir", str(tmp_path / "batches"))
    yield


def _ws(provision, db_session, monkeypatch, sub):
    ws = provision(sub=sub, email=f"{sub}@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    # Batching is a Performance-tier (behaviour-changing) lever; exercise it on a
    # Performance org.
    org = db_session.get(Organization, project.organization_id)
    org.plan_tier = "performance"
    db_session.flush()
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    return ws, project


def _seed_batch_prices(db):
    at = datetime.now(UTC) - timedelta(days=1)
    db.add(
        ModelPrice(
            model_key=MODEL,
            provider="openai",
            currency="USD",
            input_cost_per_token=Decimal("0.0000006"),
            output_cost_per_token=Decimal("0.0000024"),
            input_cost_per_token_batch=Decimal("0.0000003"),
            output_cost_per_token_batch=Decimal("0.0000012"),
            source="catalog",
            effective_at=at,
        )
    )
    db.commit()


def _output_jsonl(model: str = MODEL) -> bytes:
    lines = [
        {
            "custom_id": "a",
            "response": {
                "status_code": 200,
                "body": {"model": model, "usage": {"prompt_tokens": 1000, "completion_tokens": 500}},
            },
        },
        {
            "custom_id": "b",
            "response": {
                "status_code": 200,
                "body": {"model": model, "usage": {"prompt_tokens": 2000, "completion_tokens": 1000}},
            },
        },
    ]
    return ("\n".join(json.dumps(line) for line in lines)).encode()


def _mock_openai_batch(monkeypatch, output: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path.endswith("/v1/files") and method == "POST":
            return httpx.Response(200, json={"id": "file-in"})
        if path.endswith("/v1/batches") and method == "POST":
            return httpx.Response(200, json={"id": "batch-1", "status": "in_progress"})
        if "/content" in path and method == "GET":
            return httpx.Response(200, content=output)
        if path.startswith("/v1/batches/") and method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "batch-1",
                    "status": "completed",
                    "output_file_id": "file-out",
                    "request_counts": {"total": 2},
                },
            )
        return httpx.Response(404, json={"error": "unhandled"})

    real = httpx.AsyncClient
    monkeypatch.setattr(openai_batch.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))


# --- storage interface ----------------------------------------------------------


def test_local_storage_round_trip(tmp_path):
    s = LocalStorage(str(tmp_path / "s"))
    s.write("proj/x.jsonl", b"hello")
    assert s.exists("proj/x.jsonl")
    assert s.read("proj/x.jsonl") == b"hello"
    s.delete("proj/x.jsonl")
    assert s.exists("proj/x.jsonl") is False


def test_local_storage_rejects_traversal(tmp_path):
    s = LocalStorage(str(tmp_path / "s"))
    with pytest.raises(ValueError):
        s.write("../escape", b"x")


# --- full lifecycle -------------------------------------------------------------


def test_batch_full_lifecycle_measures_savings(client, provision, db_session, monkeypatch):
    ws, project = _ws(provision, db_session, monkeypatch, "auth0|batch")
    _seed_batch_prices(db_session)
    headers = {"Authorization": f"Bearer {ws['api_key']}"}

    # 1) Reserve a job + pre-signed upload URL.
    resp = client.post("/v1/batches/input-files", headers=headers)
    assert resp.status_code == 200
    info = resp.json()
    input_file_id = info["input_file_id"]
    assert info["upload_method"] == "PUT"

    # 2) Upload the .jsonl straight to storage (local passthrough stands in for S3).
    up = client.put(info["upload_url"], headers=headers, content=b'{"custom_id":"a"}\n')
    assert up.status_code == 200

    # 3) Create the batch (OpenAI files + batch creation mocked).
    _mock_openai_batch(monkeypatch, _output_jsonl())
    resp = client.post("/v1/batches", headers=headers, json={"input_file_id": input_file_id})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
    assert resp.json()["provider_batch_id"] == "batch-1"

    # 4) Poll: completes, finalizes, measures savings.
    resp = client.get(f"/v1/batches/{input_file_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "finalized"
    assert body["input_tokens"] == 3000 and body["output_tokens"] == 1500
    # sync = 3000*6e-7 + 1500*2.4e-6 = 0.0018 + 0.0036 = 0.0054
    # batch = 3000*3e-7 + 1500*1.2e-6 = 0.0009 + 0.0018 = 0.0027
    assert Decimal(body["naive_cost_usd"]) == Decimal("0.005400000000")
    assert Decimal(body["actual_cost_usd"]) == Decimal("0.002700000000")
    assert Decimal(body["saved_usd"]) == Decimal("0.002700000000")

    # 5) Output is downloadable, and the ledger recorded the batch savings.
    out = client.get(f"/v1/batches/{input_file_id}/output", headers=headers)
    assert out.status_code == 200 and "output_url" in out.json()

    event = db_session.scalar(
        select(UsageEvent).where(UsageEvent.project_id == project.id, UsageEvent.request_type == "batch")
    )
    assert event is not None
    assert event.event_metadata["lever"] == "batching"
    assert Decimal(event.event_metadata["saved_usd"]) == Decimal("0.0027")
    assert event.cost_usd == Decimal("0.0027")


def test_create_batch_before_upload_conflicts(client, provision, db_session, monkeypatch):
    ws, _ = _ws(provision, db_session, monkeypatch, "auth0|batch2")
    headers = {"Authorization": f"Bearer {ws['api_key']}"}
    info = client.post("/v1/batches/input-files", headers=headers).json()
    _mock_openai_batch(monkeypatch, _output_jsonl())
    # No upload happened: submit must not silently proceed.
    resp = client.post("/v1/batches", headers=headers, json={"input_file_id": info["input_file_id"]})
    assert resp.status_code == 409


def test_output_not_ready_conflicts(client, provision, db_session, monkeypatch):
    ws, _project = _ws(provision, db_session, monkeypatch, "auth0|batch3")
    headers = {"Authorization": f"Bearer {ws['api_key']}"}
    info = client.post("/v1/batches/input-files", headers=headers).json()
    resp = client.get(f"/v1/batches/{info['input_file_id']}/output", headers=headers)
    assert resp.status_code == 409


def test_batch_tenant_isolation(client, provision, db_session, monkeypatch):
    ws_a, _project_a = _ws(provision, db_session, monkeypatch, "auth0|batchA")
    ws_b, _ = _ws(provision, db_session, monkeypatch, "auth0|batchB")
    info = client.post("/v1/batches/input-files", headers={"Authorization": f"Bearer {ws_a['api_key']}"}).json()
    # B cannot read A's job.
    resp = client.get(
        f"/v1/batches/{info['input_file_id']}",
        headers={"Authorization": f"Bearer {ws_b['api_key']}"},
    )
    assert resp.status_code == 404


def test_local_upload_rejects_cross_tenant_key(client, provision, db_session, monkeypatch):
    ws_a, _ = _ws(provision, db_session, monkeypatch, "auth0|batchC")
    ws_b, _ = _ws(provision, db_session, monkeypatch, "auth0|batchD")
    info = client.post("/v1/batches/input-files", headers={"Authorization": f"Bearer {ws_a['api_key']}"}).json()
    # B tries to write to A's storage key.
    resp = client.put(info["upload_url"], headers={"Authorization": f"Bearer {ws_b['api_key']}"}, content=b"x")
    assert resp.status_code == 403


def test_engine_batches_lists_for_dashboard(client, provision, db_session, monkeypatch):
    # The dashboard reads batches via the session-authed engine endpoint, not the
    # API-key /v1/batches the client uses.
    ws, project = _ws(provision, db_session, monkeypatch, "auth0|batchE")
    job = BatchJob(
        organization_id=project.organization_id,
        project_id=project.id,
        status="finalized",
        input_storage_key="k",
        request_count=2,
        input_tokens=3000,
        output_tokens=1500,
        actual_cost_usd=Decimal("0.0027"),
        naive_cost_usd=Decimal("0.0054"),
        saved_usd=Decimal("0.0027"),
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get(
        "/v1/engine/batches",
        headers={"Authorization": f"Bearer {ws['token']}"},
        params={"project_id": str(project.id)},
    )
    assert resp.status_code == 200
    rows = resp.json()
    row = next(r for r in rows if r["id"] == str(job.id))
    assert row["status"] == "finalized"
    assert Decimal(row["saved_usd"]) == Decimal("0.0027")
    assert row["input_tokens"] == 3000


def test_unpriced_model_surfaces_no_fabricated_savings(client, provision, db_session, monkeypatch):
    ws, _project = _ws(provision, db_session, monkeypatch, "auth0|batch4")
    # A model the catalog does not cover: savings cannot be measured, must be null
    # not zero (no painted-on savings).
    headers = {"Authorization": f"Bearer {ws['api_key']}"}
    info = client.post("/v1/batches/input-files", headers=headers).json()
    client.put(info["upload_url"], headers=headers, content=b'{"custom_id":"a"}\n')
    _mock_openai_batch(monkeypatch, _output_jsonl(model="varsten-nonexistent-model-zzz"))
    client.post("/v1/batches", headers=headers, json={"input_file_id": info["input_file_id"]})
    body = client.get(f"/v1/batches/{info['input_file_id']}", headers=headers).json()
    assert body["status"] == "finalized"
    assert body["saved_usd"] is None
    assert body["input_tokens"] == 3000
