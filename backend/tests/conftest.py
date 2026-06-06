import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.db.session import async_engine, engine, get_db
from app.main import app


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
