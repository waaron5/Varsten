import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import deps
from app.db.session import engine, get_db
from app.main import app


@pytest.fixture(autouse=True)
def stub_token_verification(monkeypatch):
    """Treat a non-key bearer token as the Auth0 subject, so tests can drive the
    session-auth endpoints without a live tenant. API-key auth is unaffected: it
    short-circuits on the vk_ prefix before any token verification."""
    monkeypatch.setattr(deps, "verify_access_token", lambda token: {"sub": token})


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
        user = client.post(
            "/v1/auth/sync", headers=auth_headers(sub), json={"email": email, "name": None}
        ).json()
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
