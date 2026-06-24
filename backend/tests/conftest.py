import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps import clear_api_key_cache
from app.core.config import settings
from app.core.security import generate_api_key
from app.db.session import async_engine, engine, get_async_db, get_db
from app.main import app
from app.models import ApiKey, Organization, Project
from app.pricing.service import clear_price_cache
from app.proxy.keys import clear_provider_key_cache


@pytest.fixture(autouse=True)
def _isolate_price_cache():
    """The pricing TTL cache is process-global; clear it around each test so a
    price resolved in one test never leaks into another."""
    clear_price_cache()
    yield
    clear_price_cache()


@pytest.fixture(autouse=True)
def _isolate_provider_key_cache():
    """Provider keys and resolved proxy-key contexts are held in process-global
    caches; clear both around each test so state never leaks across test cases."""
    clear_provider_key_cache()
    clear_api_key_cache()
    yield
    clear_provider_key_cache()
    clear_api_key_cache()


@pytest.fixture(autouse=True)
def _disable_network_side_effects(monkeypatch):
    """Provider-key validation makes a real network probe; disable it by default so
    tests never hit a provider. Tests that exercise validation enable + mock it.
    Also reset the in-memory rate limiter so windows never bleed across tests."""
    from app.auth.entitlements import invalidate_plan_tier
    from app.core import ratelimit

    monkeypatch.setattr(settings, "provider_key_validation_enabled", False)
    ratelimit.reset_all()
    invalidate_plan_tier()
    yield
    ratelimit.reset_all()
    invalidate_plan_tier()


@pytest.fixture(autouse=True)
def stub_token_verification(monkeypatch, tmp_path):
    """Treat a non-key bearer token as the Auth0 subject, so tests can drive the
    session-auth endpoints without a live tenant. API-key auth is unaffected: it
    short-circuits on the vk_ prefix before any token verification.

    Also redirects the failure registry to a per-test temp file so test losses
    never pollute the production golden dataset."""
    monkeypatch.setattr(deps, "verify_access_token", lambda token: {"sub": token})
    monkeypatch.setattr(settings, "eval_failure_registry_path", str(tmp_path / "test_failures.jsonl"))


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def provision(client):
    """Provision an authenticated workspace: sync a user (which bootstraps their
    personal org), then create a project and an API key in it, all through the
    real authenticated endpoints. Returns the identifiers tests need."""

    def _provision(
        sub: str = "auth0|owner",
        email: str = "owner@example.com",
        project_name: str = "prod",
    ) -> dict:
        user = client.post("/v1/auth/sync", headers=auth_headers(sub), json={"email": email, "name": None}).json()
        org_id = user["organizations"][0]["id"]
        project = client.post(
            f"/v1/organizations/{org_id}/projects",
            headers=auth_headers(sub),
            json={"name": project_name},
        ).json()
        key = client.post(
            f"/v1/projects/{project['id']}/api-keys",
            headers=auth_headers(sub),
            json={"name": "ingest"},
        ).json()
        return {
            "sub": sub,
            "token": sub,
            "org_id": org_id,
            "project_id": project["id"],
            "api_key": key["plaintext_key"],
        }

    return _provision


@pytest.fixture
def db_session():
    """A session wrapped in an outer transaction that is rolled back after each
    test. join_transaction_mode="create_savepoint" lets endpoint commits land as
    savepoints, so nothing touches committed dev data."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- async DB stack (Step 1 of the async migration) ---------------------------


@pytest.fixture
def anyio_backend():
    """Pin anyio-marked async tests to asyncio (trio is not a dependency)."""
    return "asyncio"


@pytest.fixture
async def async_db_session():
    """Async analogue of db_session. An AsyncSession bound to a connection wrapped
    in an outer transaction that is rolled back after each test, with
    join_transaction_mode="create_savepoint" so a session.commit() inside an
    endpoint lands as a savepoint and never touches committed data. This is the
    async stack the proxy hot path migrates onto in Step 2; proving it here first
    de-risks the repo-wide conversion."""
    connection = await async_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
async def async_client(async_db_session):
    """httpx AsyncClient over the ASGI app, with the async DB dependency pointed at
    the test's savepoint-isolated session so endpoint writes and test assertions
    share one transaction. For endpoints on the async stack (the inline proxy)."""
    app.dependency_overrides[get_async_db] = lambda: async_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def async_provision(async_db_session):
    """Provision an org + project + API key directly through the async session.
    The sync HTTP provisioning runs on a separate connection the async route cannot
    see (sync and async psycopg connections do not share a transaction), so async
    endpoint tests must provision on the same async session they assert on."""

    async def _provision(
        sub: str | None = None,
        email: str | None = None,
        project_name: str = "prod",
        plan_tier: str = "performance",
    ) -> dict:
        # Async proxy tests exercise optimization (cache/route/trim), which is
        # Performance-only now that Free is observe-only, so default to Performance.
        # Observe-only tests pass plan_tier="free" explicitly.
        org = Organization(name="async-test-org", plan_tier=plan_tier)
        async_db_session.add(org)
        await async_db_session.flush()
        project = Project(organization_id=org.id, name=project_name)
        async_db_session.add(project)
        await async_db_session.flush()
        plaintext, prefix, key_hash = generate_api_key()
        api_key = ApiKey(project_id=project.id, name="ingest", key_prefix=prefix, key_hash=key_hash)
        async_db_session.add(api_key)
        await async_db_session.flush()
        return {
            "org_id": str(org.id),
            "project_id": str(project.id),
            "api_key": plaintext,
            "api_key_id": api_key.id,
        }

    return _provision
