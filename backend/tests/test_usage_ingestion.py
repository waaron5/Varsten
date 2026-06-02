"""Integration tests for the ingestion endpoint's cost derivation and idempotency.

Uses the API-key path. A ModelPrice row is inserted via the same test session so
the endpoint can derive cost; the client and db_session share one transaction.
"""
from decimal import Decimal

from app.models import ModelPrice


def _key(client) -> str:
    org = client.post("/v1/organizations", json={"name": "C"}).json()
    proj = client.post(
        f"/v1/organizations/{org['id']}/projects", json={"name": "p"}
    ).json()
    key = client.post(
        f"/v1/projects/{proj['id']}/api-keys", json={"name": "k"}
    ).json()
    return key["plaintext_key"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_price(db, model_key="gpt-4o-mini", provider="openai"):
    db.add(
        ModelPrice(
            model_key=model_key,
            provider=provider,
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000002"),
        )
    )
    db.flush()


def _event(**overrides) -> dict:
    body = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completion",
        "input_tokens": 1000,
        "output_tokens": 500,
    }
    body.update(overrides)
    return body


def test_derives_cost_for_known_model(client, db_session):
    _seed_price(db_session)
    token = _key(client)

    res = client.post("/v1/usage-events", headers=_bearer(token), json=_event())
    assert res.status_code == 201
    body = res.json()
    assert body["cost_source"] == "derived"
    assert body["price_version_id"] is not None
    # 1000*1e-6 + 500*2e-6 = 0.002
    assert Decimal(body["cost_usd"]) == Decimal("0.002")
    assert body["reported_cost_usd"] is None


def test_falls_back_to_reported_cost_for_unknown_model(client, db_session):
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model", cost_usd="0.0042"),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["cost_source"] == "reported"
    assert body["price_version_id"] is None
    assert Decimal(body["cost_usd"]) == Decimal("0.0042")
    assert Decimal(body["reported_cost_usd"]) == Decimal("0.0042")


def test_unpriceable_event_is_rejected(client, db_session):
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model"),  # no price, no cost_usd
    )
    assert res.status_code == 422


def test_non_usd_is_rejected(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    res = client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(currency="EUR"),
    )
    assert res.status_code == 422


def test_idempotency_key_dedupes_retries(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    payload = _event(idempotency_key="abc-123")

    first = client.post("/v1/usage-events", headers=_bearer(token), json=payload)
    second = client.post("/v1/usage-events", headers=_bearer(token), json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listed = client.get("/v1/usage-events", headers=_bearer(token)).json()
    assert len(listed["items"]) == 1


def test_overview_reports_cost_trust_share(client, db_session):
    _seed_price(db_session)
    token = _key(client)
    # One derived event (0.002) and one reported event (0.002).
    client.post("/v1/usage-events", headers=_bearer(token), json=_event())
    client.post(
        "/v1/usage-events",
        headers=_bearer(token),
        json=_event(model="mystery-model", cost_usd="0.002"),
    )

    overview = client.get("/v1/metrics/overview", headers=_bearer(token)).json()
    assert Decimal(overview["authoritative_spend_month"]) == Decimal("0.002")
    # Half of spend is authoritative (derived), half reported.
    assert Decimal(overview["authoritative_spend_share_month"]) == Decimal("0.5")
