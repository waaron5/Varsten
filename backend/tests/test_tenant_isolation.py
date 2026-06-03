"""Tenant isolation: management endpoints must reject unauthenticated access and
refuse every cross-tenant create, read, or mutate. These guard the holes that
blocked onboarding a real client (notably unauthenticated API-key creation)."""


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_management_endpoints_rejected(client, provision):
    a = provision(sub="auth0|a", email="a@example.com")

    # No bearer token -> 401 on every management route, including the worst one
    # (minting an API key, which would otherwise grant a tenant's data).
    assert client.post("/v1/organizations", json={"name": "x"}).status_code == 401
    assert client.get("/v1/organizations").status_code == 401
    assert (
        client.post(f"/v1/organizations/{a['org_id']}/projects", json={"name": "x"}).status_code
        == 401
    )
    assert (
        client.post(f"/v1/projects/{a['project_id']}/api-keys", json={"name": "x"}).status_code
        == 401
    )
    assert client.get(f"/v1/projects/{a['project_id']}/api-keys").status_code == 401


def test_list_organizations_scoped_to_caller(client, provision):
    a = provision(sub="auth0|a", email="a@example.com")
    b = provision(sub="auth0|b", email="b@example.com")

    a_ids = {o["id"] for o in client.get("/v1/organizations", headers=_b("auth0|a")).json()}
    b_ids = {o["id"] for o in client.get("/v1/organizations", headers=_b("auth0|b")).json()}

    assert a["org_id"] in a_ids and a["org_id"] not in b_ids
    assert b["org_id"] in b_ids and b["org_id"] not in a_ids


def test_cannot_create_project_in_other_org(client, provision):
    a = provision(sub="auth0|a", email="a@example.com")
    provision(sub="auth0|b", email="b@example.com")

    res = client.post(
        f"/v1/organizations/{a['org_id']}/projects",
        headers=_b("auth0|b"),
        json={"name": "intruder"},
    )
    assert res.status_code == 403


def test_cannot_touch_other_projects_keys_or_data(client, provision):
    a = provision(sub="auth0|a", email="a@example.com")
    provision(sub="auth0|b", email="b@example.com")

    # Mint, list, and read on A's project, all as B.
    assert (
        client.post(
            f"/v1/projects/{a['project_id']}/api-keys", headers=_b("auth0|b"), json={"name": "x"}
        ).status_code
        == 403
    )
    assert (
        client.get(f"/v1/projects/{a['project_id']}/api-keys", headers=_b("auth0|b")).status_code
        == 403
    )
    assert client.get(f"/v1/projects/{a['project_id']}", headers=_b("auth0|b")).status_code == 403


def test_cannot_revoke_other_api_key(client, provision):
    a = provision(sub="auth0|a", email="a@example.com")
    provision(sub="auth0|b", email="b@example.com")

    keys = client.get(f"/v1/projects/{a['project_id']}/api-keys", headers=_b("auth0|a")).json()
    key_id = keys[0]["id"]

    assert client.delete(f"/v1/api-keys/{key_id}", headers=_b("auth0|b")).status_code == 403
    # And A can still revoke their own.
    assert client.delete(f"/v1/api-keys/{key_id}", headers=_b("auth0|a")).status_code == 200
