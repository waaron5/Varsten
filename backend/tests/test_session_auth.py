"""Integration tests for Auth0 session auth and project authorization.

Runs against the local Postgres (rolled back per test). verify_access_token is
stubbed so the token string is treated as the Auth0 subject, exercising the
sync/require_user/resolve_project logic without a live tenant.
"""

import pytest

from app.api import deps


@pytest.fixture(autouse=True)
def stub_token_verification(monkeypatch):
    # The bearer token string is the `sub`. Session tokens must not look like an
    # API key (no "vk_" prefix), matching the real discriminator.
    monkeypatch.setattr(deps, "verify_access_token", lambda token: {"sub": token})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sync(client, sub: str, email: str, name: str | None = None):
    return client.post("/v1/auth/sync", headers=bearer(sub), json={"email": email, "name": name})


def test_sync_creates_user_with_personal_org(client):
    res = sync(client, "auth0|alice", "alice@example.com", "Alice")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "alice@example.com"
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["name"] == "alice's workspace"

    me = client.get("/v1/auth/me", headers=bearer("auth0|alice"))
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


def test_sync_is_idempotent(client):
    first = sync(client, "auth0|bob", "bob@example.com", "Bob").json()
    second = sync(client, "auth0|bob", "bob@example.com", "Bobby").json()
    assert first["id"] == second["id"]
    assert second["name"] == "Bobby"
    assert len(second["organizations"]) == 1  # no duplicate org on re-sync


def test_list_my_projects(client):
    user = sync(client, "auth0|carol", "carol@example.com").json()
    org_id = user["organizations"][0]["id"]
    proj = client.post(
        f"/v1/organizations/{org_id}/projects",
        headers=bearer("auth0|carol"),
        json={"name": "prod"},
    ).json()

    res = client.get("/v1/projects", headers=bearer("auth0|carol"))
    assert res.status_code == 200
    assert [p["id"] for p in res.json()] == [proj["id"]]


def test_session_read_requires_project_id(client):
    sync(client, "auth0|dana", "dana@example.com")
    res = client.get("/v1/metrics/overview", headers=bearer("auth0|dana"))
    assert res.status_code == 400


def test_session_read_authorized_for_own_project(client):
    user = sync(client, "auth0|erin", "erin@example.com").json()
    org_id = user["organizations"][0]["id"]
    proj = client.post(
        f"/v1/organizations/{org_id}/projects",
        headers=bearer("auth0|erin"),
        json={"name": "prod"},
    ).json()

    res = client.get(
        "/v1/metrics/overview",
        headers=bearer("auth0|erin"),
        params={"project_id": proj["id"]},
    )
    assert res.status_code == 200
    assert res.json()["requests_today"] == 0


def test_session_read_forbidden_for_other_org_project(client):
    sync(client, "auth0|frank", "frank@example.com")
    # A project in an organization frank is not a member of, owned by another user.
    other = sync(client, "auth0|other", "other@example.com").json()
    other_org_id = other["organizations"][0]["id"]
    other_proj = client.post(
        f"/v1/organizations/{other_org_id}/projects",
        headers=bearer("auth0|other"),
        json={"name": "secret"},
    ).json()

    res = client.get(
        "/v1/metrics/overview",
        headers=bearer("auth0|frank"),
        params={"project_id": other_proj["id"]},
    )
    assert res.status_code == 403


def test_unsynced_user_rejected(client):
    res = client.get("/v1/projects", headers=bearer("auth0|ghost"))
    assert res.status_code == 401


def test_api_key_read_path_still_works(client):
    user = sync(client, "auth0|keyco", "keyco@example.com").json()
    org_id = user["organizations"][0]["id"]
    proj = client.post(
        f"/v1/organizations/{org_id}/projects",
        headers=bearer("auth0|keyco"),
        json={"name": "prod"},
    ).json()
    key = client.post(
        f"/v1/projects/{proj['id']}/api-keys",
        headers=bearer("auth0|keyco"),
        json={"name": "ingest"},
    ).json()

    # API key path: no project_id needed, project derived from the key.
    res = client.get("/v1/metrics/overview", headers=bearer(key["plaintext_key"]))
    assert res.status_code == 200
