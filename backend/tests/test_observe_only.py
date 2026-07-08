"""Observe-only (Free) proxy behavior + operator plan switch.

Free is observe-only: the proxy meters and records, but does not serve or store
the cache, so a repeat request still hits the upstream and accrues no captured
savings. Optimize caches as before.
"""

import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import ProxyCacheEntry, UsageEvent
from app.proxy import circuit, http_client
from tests.conftest import auth_headers

CHAT = "gpt-4o-mini"


@pytest.fixture(autouse=True)
def _reset_circuit():
    circuit.reset_all()
    yield
    circuit.reset_all()


@pytest.fixture
def mock_openai(monkeypatch):
    calls = {"completions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["completions"] += 1
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "model": CHAT,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return calls


def _body():
    return {"model": CHAT, "messages": [{"role": "user", "content": "same prompt"}]}


@pytest.mark.anyio
async def test_free_does_not_cache_or_capture_savings(
    async_client, async_provision, async_db_session, monkeypatch, mock_openai
):
    p = await async_provision(plan_tier="free")
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    headers = {"Authorization": f"Bearer {p['api_key']}"}

    r1 = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    r2 = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.headers.get("X-Varsten-Mode") == "observe"
    assert r1.headers.get("X-Varsten-Cache") == "off"

    # Both requests hit the upstream (no cache serve), nothing was cached, and no
    # saved_usd was recorded (no captured savings on Free).
    assert mock_openai["completions"] == 2
    entries = await async_db_session.scalar(
        select(func.count())
        .select_from(ProxyCacheEntry)
        .where(ProxyCacheEntry.project_id == uuid.UUID(p["project_id"]))
    )
    assert entries == 0
    events = list(
        await async_db_session.scalars(select(UsageEvent).where(UsageEvent.project_id == uuid.UUID(p["project_id"])))
    )
    assert len(events) == 2
    assert all((e.event_metadata or {}).get("saved_usd") in (None, "0", "0.0") for e in events)


@pytest.mark.anyio
async def test_observe_only_async_fails_open_to_observe():
    """If the plan lookup itself errors, the org is treated as observe-only, never
    Optimize."""
    from app.auth.entitlements import invalidate_plan_tier, observe_only_async

    invalidate_plan_tier()

    class _BoomDB:
        async def get(self, *args, **kwargs):
            raise RuntimeError("db down")

    assert await observe_only_async(_BoomDB(), uuid.uuid4()) is True


@pytest.mark.anyio
async def test_proxy_fails_open_to_observe_only(async_client, async_provision, monkeypatch, mock_openai):
    """The exact fail-open contract: when the tier lookup raises, the request still
    succeeds (traffic never blocked) but behaviour-changing optimization stays off —
    even on an Optimize org, caching does not kick in."""
    p = await async_provision(plan_tier="performance")
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})

    async def boom(db, organization_id):
        raise RuntimeError("plan lookup failed")

    monkeypatch.setattr("app.proxy.router.observe_only_async", boom)
    headers = {"Authorization": f"Bearer {p['api_key']}"}

    r1 = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    r2 = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    # Traffic succeeds despite the failed lookup...
    assert r1.status_code == 200 and r2.status_code == 200
    # ...and behaves observe-only (no caching), not Optimize.
    assert r1.headers.get("X-Varsten-Mode") == "observe"
    assert mock_openai["completions"] == 2


@pytest.mark.anyio
async def test_performance_caches(async_client, async_provision, monkeypatch, mock_openai):
    p = await async_provision(plan_tier="performance")
    monkeypatch.setattr(settings, "proxy_openai_keys", {p["project_id"]: "sk-test"})
    headers = {"Authorization": f"Bearer {p['api_key']}"}

    await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    r2 = await async_client.post("/v1/chat/completions", headers=headers, json=_body())
    # Second identical request served from cache: upstream called once only.
    assert mock_openai["completions"] == 1
    assert r2.headers.get("X-Varsten-Cache") == "hit"


# --- operator plan switch (dev tooling) --------------------------------------


def test_operator_can_switch_plan(client, provision, db_session, monkeypatch):
    p = provision(sub="auth0|op", email="op@example.com")
    monkeypatch.setattr(settings, "operator_admin_emails", ["op@example.com"])

    resp = client.post(
        f"/v1/operator/organizations/{p['org_id']}/plan",
        headers=auth_headers(p["token"]),
        json={"plan_tier": "performance"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan_tier"] == "performance"

    # And entitlements reflect it.
    ent = client.get(f"/v1/entitlements?project_id={p['project_id']}", headers=auth_headers(p["token"])).json()
    assert ent["plan_tier"] == "performance"


def test_non_operator_cannot_switch_plan(client, provision, db_session, monkeypatch):
    p = provision(sub="auth0|notop", email="notop@example.com")
    monkeypatch.setattr(settings, "operator_admin_emails", ["someone-else@example.com"])
    resp = client.post(
        f"/v1/operator/organizations/{p['org_id']}/plan",
        headers=auth_headers(p["token"]),
        json={"plan_tier": "performance"},
    )
    assert resp.status_code == 403


def test_operator_rejects_bad_tier(client, provision, db_session, monkeypatch):
    p = provision(sub="auth0|op2", email="op2@example.com")
    monkeypatch.setattr(settings, "operator_admin_emails", ["op2@example.com"])
    resp = client.post(
        f"/v1/operator/organizations/{p['org_id']}/plan",
        headers=auth_headers(p["token"]),
        json={"plan_tier": "enterprise"},
    )
    assert resp.status_code == 422
