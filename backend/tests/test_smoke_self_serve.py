"""End-to-end self-serve smoke walkthrough.

Drives the real authenticated endpoints through the full funnel a new customer
hits: signup -> trial -> default project -> API key -> provider connect -> snippet
event -> first request -> dashboard/trial state -> expiry fallback -> Stripe upgrade
-> billing-flag/production-readiness gating. Each numbered step prints PASS so the
run doubles as a deploy-time smoke report.

Reuses the suite's harness (savepoint-isolated DB, stubbed Auth0 token, disabled
provider probe). The proxy first request and the Stripe SDK calls are mocked; every
billing-state transition and entitlement decision is exercised for real.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import stripe_billing
from app.api.v1 import projects as project_routes
from app.core.config import settings, validate_production
from app.models import (
    PLAN_FREE,
    PLAN_PERFORMANCE,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_TRIALING,
    Organization,
    Project,
    UsageEvent,
)
from tests.conftest import auth_headers

WEBHOOK_SECRET = "whsec_smoke_secret"


def _say(step: int, msg: str) -> None:
    print(f"[PASS] {step:>2}. {msg}")


def test_self_serve_smoke(client, db_session, monkeypatch):
    sub = "auth0|smoke"

    # 13a (checked first, while billing is disabled by default): upgrade is gated off.
    # Done before enabling Stripe so we observe the real disabled-state behaviour.

    # 1. New user signs up via /start -> the frontend calls POST /auth/sync.
    synced = client.post(
        "/v1/auth/sync", headers=auth_headers(sub), json={"email": "smoke@example.com", "name": "Smoke"}
    ).json()
    org_id = synced["organizations"][0]["id"]
    org = db_session.get(Organization, uuid.UUID(org_id))
    _say(1, f"signup created user + org {org_id}")

    # 2. New org is performance + trialing.
    assert org.plan_tier == PLAN_PERFORMANCE
    assert org.subscription_status == SUBSCRIPTION_TRIALING
    _say(2, "org is performance + trialing")

    # 3. trial_started_at / trial_ends_at populated, ~14 days apart.
    assert org.trial_started_at is not None and org.trial_ends_at is not None
    span = org.trial_ends_at - org.trial_started_at
    assert timedelta(days=13) < span < timedelta(days=15)
    _say(3, f"trial window populated ({span.days}d)")

    # 4. Default Production project exists automatically.
    projects = list(db_session.scalars(select(Project).where(Project.organization_id == org.id)))
    assert len(projects) == 1 and projects[0].name == "Production"
    project_id = str(projects[0].id)
    _say(4, "default Production project created")

    # 5. Onboarding does not dead-end: GET /projects (what the client uses to pick
    #    activeProjectId) returns it, and onboarding/status resolves for that project.
    listed = client.get("/v1/projects", headers=auth_headers(sub)).json()
    assert any(p["id"] == project_id for p in listed)
    status = client.get(f"/v1/onboarding/status?project_id={project_id}", headers=auth_headers(sub)).json()
    assert status["has_project"] is True
    _say(5, "activeProjectId resolvable; onboarding status loads")

    # 6. Create a Varsten API key.
    key = client.post(f"/v1/projects/{project_id}/api-keys", headers=auth_headers(sub), json={"name": "default"}).json()
    assert key["plaintext_key"].startswith("vk_")
    _say(6, "Varsten API key created")

    # 7. Connect a provider key via the self-serve path (vault write stubbed).
    monkeypatch.setattr(
        project_routes,
        "store_provider_key_for_project",
        lambda pid, provider, api_key: f"localdb:v1:smoke/{pid}/{provider}",
    )
    conn = client.post(
        f"/v1/projects/{project_id}/connections",
        headers=auth_headers(sub),
        json={"provider": "openai", "api_key": "sk-smoke"},
    )
    assert conn.status_code == 200 and conn.json()["status"] == "connected"
    assert (
        client.get(f"/v1/onboarding/status?project_id={project_id}", headers=auth_headers(sub)).json()[
            "has_provider_connection"
        ]
        is True
    )
    _say(7, "provider key connected; onboarding reflects it")

    # 8. Copy the integration snippet -> onboarding event recorded.
    client.post(
        f"/v1/onboarding/event?project_id={project_id}",
        headers=auth_headers(sub),
        json={"event": "snippet_viewed"},
    )
    assert (
        client.get(f"/v1/onboarding/status?project_id={project_id}", headers=auth_headers(sub)).json()[
            "integration_snippet_viewed"
        ]
        is True
    )
    _say(8, "snippet_viewed event recorded")

    # 9. First request through the gateway (mocked: write the proxy ledger row the
    #    gateway would write) -> onboarding first-request detection flips.
    db_session.add(
        UsageEvent(
            project_id=uuid.UUID(project_id),
            organization_id=org.id,
            provider="openai",
            model="gpt-4o-mini",
            operation="chat_completion",
            source="proxy",
            environment="production",
            input_tokens=10,
            output_tokens=4,
            total_tokens=14,
            cost_source="catalog",
            pricing_status="priced",
            latency_ms=120,
            received_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    assert (
        client.get(f"/v1/onboarding/status?project_id={project_id}", headers=auth_headers(sub)).json()["first_request"][
            "seen"
        ]
        is True
    )
    _say(9, "first gateway request detected (mocked ledger write)")

    # 10. Dashboard shows trial mode + Performance access.
    ent = client.get(f"/v1/entitlements?project_id={project_id}", headers=auth_headers(sub)).json()
    assert ent["plan_tier"] == PLAN_PERFORMANCE and ent["observe_only"] is False
    assert ent["trial"]["trial_ends_at"] is not None and ent["trial"]["trial_expired"] is False
    assert ent["features"]["apply_recommendations"] is True
    _say(10, "entitlements: Performance unlocked, trial active")

    # 13b. Upgrade actions are gated off while billing is disabled (default).
    disabled_checkout = client.post(f"/v1/organizations/{org_id}/billing/checkout-session", headers=auth_headers(sub))
    assert disabled_checkout.status_code == 503
    _say(13, "billing disabled -> checkout endpoint 503 (frontend hides upgrade)")

    # 11. Force the trial to expire -> Free observe-only, without blocking traffic.
    org.trial_ends_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    stripe_billing.billing_lifecycle._invalidate(org.id)
    ent_expired = client.get(f"/v1/entitlements?project_id={project_id}", headers=auth_headers(sub)).json()
    assert ent_expired["observe_only"] is True and ent_expired["plan_tier"] == PLAN_FREE
    assert ent_expired["features"]["enable_routing"] is False  # optimization locked
    # Visibility/metering surface still serves (traffic/observe path not blocked).
    assert client.get(f"/v1/onboarding/status?project_id={project_id}", headers=auth_headers(sub)).status_code == 200
    db_session.refresh(org)
    assert org.subscription_status == SUBSCRIPTION_EXPIRED
    _say(11, "expired trial -> Free observe-only; metering still serves")

    # 14. Production readiness FAILS only when billing is on but Stripe config missing.
    s_off = settings.model_copy(update={"self_serve_billing_enabled": False})
    assert not [p for p in validate_production(s_off) if "STRIPE" in p]
    s_on_missing = settings.model_copy(
        update={"self_serve_billing_enabled": True, "stripe_secret_key": "", "stripe_webhook_secret": ""}
    )
    stripe_problems = [p for p in validate_production(s_on_missing) if "STRIPE" in p]
    assert len(stripe_problems) == 2
    _say(14, "validate_production: clean when billing off, flags Stripe only when on+missing")

    # 13c. Confirm a billing-disabled production config has no Stripe blockers (boots).
    _say(13, "billing disabled -> production boots without Stripe config")

    # 12. Stripe setup mode (test mode). Enable billing + stub the SDK network calls.
    monkeypatch.setattr(settings, "self_serve_billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_smoke")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(stripe_billing.stripe.Customer, "create", lambda **kw: {"id": "cus_smoke"})
    monkeypatch.setattr(stripe_billing.stripe.checkout.Session, "create", lambda **kw: {"url": "https://co.stripe/x"})
    monkeypatch.setattr(
        stripe_billing.stripe.billing_portal.Session, "create", lambda **kw: {"url": "https://portal.stripe/x"}
    )

    checkout = client.post(f"/v1/organizations/{org_id}/billing/checkout-session", headers=auth_headers(sub))
    assert checkout.status_code == 200 and checkout.json()["url"] == "https://co.stripe/x"
    db_session.refresh(org)
    assert org.stripe_customer_id == "cus_smoke"
    _say(12, "checkout session starts; Stripe customer linked")

    event = {
        "id": "evt_smoke",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"object": "checkout.session", "customer": "cus_smoke"}},
    }
    payload = json.dumps(event).encode()
    ts = int(time.time())
    sig = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    good = client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": f"t={ts},v1={sig}"})
    assert good.status_code == 200 and good.json()["handled"] is True
    bad = client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": "t=1,v1=bad"})
    assert bad.status_code == 400
    db_session.refresh(org)
    assert org.plan_tier == PLAN_PERFORMANCE and org.subscription_status == SUBSCRIPTION_ACTIVE
    _say(12, "webhook verifies signature; payment method activates Performance")

    portal = client.post(f"/v1/organizations/{org_id}/billing/portal-session", headers=auth_headers(sub))
    assert portal.status_code == 200 and portal.json()["url"] == "https://portal.stripe/x"
    _say(12, "billing portal opens for existing Stripe customer")

    print("\nALL SELF-SERVE SMOKE STEPS PASSED")
