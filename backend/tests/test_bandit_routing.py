"""Bandit routing over eval-cleared candidates (phase E).

The sampler only ever chooses within a policy's eval-cleared candidate set,
under a sampled quality floor and an explicit exploration budget; everything it
learns from is a persisted ledger aggregate, and everything it does lands back
in the ledger. Default off; shadow mode changes telemetry only; drift removes a
regressed candidate surgically.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine import bandit
from app.engine.priors import candidate_stats_for_request, clear_outcome_prior_cache
from app.models import (
    ChangeRequest,
    EngineOutcomePrior,
    EvalRun,
    ModelPrice,
    Project,
    ProxyPolicy,
    Recommendation,
    RecommendationAction,
    RequestDecisionEvent,
    UsageEvent,
    User,
)
from app.models.eval import RUN_COMPLETED, VERDICT_NEEDS_HUMAN, VERDICT_SAFE, VERDICT_UNSAFE
from app.proxy import drift as drift_mod
from app.proxy import http_client, routing
from app.savings import month_start

INCUMBENT = "gpt-4o"
PRIMARY = "gpt-4o-mini"
CHALLENGER = "gpt-4.1-mini"


def _stats(model, *, n=100, quality=1.0, savings="0.01", provider="openai") -> bandit.CandidateStats:
    return bandit.CandidateStats(
        model=model,
        provider=provider,
        sample_count=n,
        quality_pass_rate=quality,
        average_savings_usd=Decimal(savings) if savings is not None else None,
    )


# --- sampler ---------------------------------------------------------------------


def test_empty_candidates_falls_back_to_primary():
    choice = bandit.select_candidate(PRIMARY, "openai", [])
    assert choice.model == PRIMARY
    assert choice.reason == "fallback_primary"


def test_exploit_picks_highest_measured_savings():
    candidates = [
        _stats(PRIMARY, n=1000, quality=1.0, savings="0.010"),
        _stats(CHALLENGER, n=1000, quality=1.0, savings="0.020"),
    ]
    choice = bandit.select_candidate(PRIMARY, "openai", candidates)
    assert choice.model == CHALLENGER
    assert choice.reason == "exploit"


def test_bad_quality_candidate_never_wins():
    # 50% measured quality over 1000 samples: its Beta draw cannot clear a 0.95
    # floor in practice, however good its savings look.
    candidates = [
        _stats(PRIMARY, n=1000, quality=1.0, savings="0.010"),
        _stats(CHALLENGER, n=1000, quality=0.5, savings="0.500"),
    ]
    for _ in range(50):
        choice = bandit.select_candidate(PRIMARY, "openai", candidates)
        assert choice.model == PRIMARY


def test_exploration_budget_routes_to_unproven(monkeypatch):
    monkeypatch.setattr(settings, "bandit_exploration_budget", 1.0)  # force explore
    candidates = [
        _stats(PRIMARY, n=1000, quality=1.0, savings="0.010"),
        _stats(CHALLENGER, n=0, quality=None, savings=None),  # cold: no evidence
    ]
    # The cold candidate draws from Beta(1,1); retry until its draw clears the
    # floor (p ~ 0.05/try) to verify the explore path targets it.
    for _ in range(500):
        choice = bandit.select_candidate(PRIMARY, "openai", candidates)
        if choice.reason == "explore":
            assert choice.model == CHALLENGER
            return
        assert choice.model == PRIMARY  # floor-failed cold draw: honest fallback
    pytest.fail("exploration never selected the unproven candidate")


def test_zero_exploration_budget_never_explores(monkeypatch):
    monkeypatch.setattr(settings, "bandit_exploration_budget", 0.0)
    candidates = [
        _stats(PRIMARY, n=1000, quality=1.0, savings="0.010"),
        _stats(CHALLENGER, n=0, quality=None, savings=None),
    ]
    for _ in range(100):
        assert bandit.select_candidate(PRIMARY, "openai", candidates).reason != "explore"


def test_mode_parsing(monkeypatch):
    monkeypatch.setattr(settings, "bandit_routing_mode", "off")
    assert bandit.mode() == bandit.MODE_OFF
    monkeypatch.setattr(settings, "bandit_routing_mode", "SHADOW")
    assert bandit.mode() == bandit.MODE_SHADOW
    monkeypatch.setattr(settings, "bandit_routing_mode", "bogus")
    assert bandit.mode() == bandit.MODE_OFF


# --- persisted candidate stats ----------------------------------------------------


def _prior_row(project, *, model_chosen, task_type="classification.intent", n=50, quality="0.99", avg="0.02"):
    return EngineOutcomePrior(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        task_type=task_type,
        risk_level="low",
        provider_requested="openai",
        model_requested=INCUMBENT,
        provider_chosen="openai",
        model_chosen=model_chosen,
        readiness_status="recommendable",
        sample_count=n,
        measured_savings_count=n,
        total_gross_savings_usd=Decimal(avg) * n,
        average_gross_savings_usd=Decimal(avg),
        quality_pass_rate=Decimal(quality),
        feedback_acceptance_rate=Decimal("1.0"),
        reason_codes=[],
        window_days=30,
        computed_at=datetime.now(UTC),
    )


@pytest.mark.anyio
async def test_candidate_stats_merge_across_segments(async_provision, async_db_session):
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    # Two segments for the same candidate: merged sample-weighted.
    async_db_session.add(_prior_row(project, model_chosen=PRIMARY, task_type="a", n=30, quality="1.0", avg="0.01"))
    async_db_session.add(_prior_row(project, model_chosen=PRIMARY, task_type="b", n=10, quality="0.9", avg="0.03"))
    await async_db_session.flush()
    clear_outcome_prior_cache()

    stats = await candidate_stats_for_request(async_db_session, project.id, INCUMBENT)
    assert len(stats) == 1
    merged = stats[0]
    assert merged.model == PRIMARY
    assert merged.sample_count == 40
    assert abs(merged.quality_pass_rate - 0.975) < 1e-9  # (30*1.0 + 10*0.9) / 40
    assert merged.average_savings_usd == Decimal("0.015")  # (30*.01 + 10*.03) / 40


# --- resolve_route integration -----------------------------------------------------


def _policy(project, *, params_extra=None, **kw):
    params = {"candidate_model": PRIMARY, **(params_extra or {})}
    return ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=INCUMBENT,
        params=params,
        enabled=True,
        holdback_percent=Decimal("0"),
        **kw,
    )


def _bandit_params():
    return {"bandit_candidates": [{"model": CHALLENGER, "provider": "openai"}]}


async def _seed_winning_challenger(async_db_session, project):
    async_db_session.add(_prior_row(project, model_chosen=PRIMARY, n=100, quality="1.0", avg="0.01"))
    async_db_session.add(_prior_row(project, model_chosen=CHALLENGER, n=100, quality="1.0", avg="0.05"))
    await async_db_session.flush()
    clear_outcome_prior_cache()


@pytest.mark.anyio
async def test_resolve_route_off_mode_is_untouched(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "bandit_routing_mode", "off")
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, params_extra=_bandit_params()))
    await async_db_session.flush()
    await _seed_winning_challenger(async_db_session, project)

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision.candidate_model == PRIMARY
    assert decision.bandit_trace is None


@pytest.mark.anyio
async def test_resolve_route_shadow_traces_but_routes_primary(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "bandit_routing_mode", "shadow")
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, params_extra=_bandit_params()))
    await async_db_session.flush()
    await _seed_winning_challenger(async_db_session, project)

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision.candidate_model == PRIMARY  # traffic unchanged
    assert decision.bandit_trace is not None
    assert decision.bandit_trace["mode"] == "shadow"
    assert decision.bandit_trace["chosen_model"] == CHALLENGER  # would-be pick


@pytest.mark.anyio
async def test_resolve_route_active_routes_to_bandit_choice(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "bandit_routing_mode", "active")
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, params_extra=_bandit_params()))
    await async_db_session.flush()
    await _seed_winning_challenger(async_db_session, project)

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision.candidate_model == CHALLENGER
    assert decision.bandit_trace["mode"] == "active"
    assert decision.bandit_trace["reason"] == "exploit"


@pytest.mark.anyio
async def test_resolve_route_bandit_failure_falls_back_to_primary(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "bandit_routing_mode", "active")

    async def _boom(*args, **kwargs):
        raise RuntimeError("stats exploded")

    monkeypatch.setattr(routing, "candidate_stats_for_request", _boom)
    ws = await async_provision()
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    async_db_session.add(_policy(project, params_extra=_bandit_params()))
    await async_db_session.flush()

    decision = await routing.resolve_route(async_db_session, project.id, INCUMBENT, {"messages": []})
    assert decision is not None
    assert decision.candidate_model == PRIMARY
    assert decision.bandit_trace is None


# --- clearance gate ----------------------------------------------------------------


def _sync_project(db_session, provision, **kw):
    p = provision(**kw)
    return p, db_session.get(Project, uuid.UUID(p["project_id"]))


def _sync_policy(db_session, project) -> ProxyPolicy:
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever="model_downshift",
        target_type="model",
        target_key=INCUMBENT,
        params={"candidate_model": PRIMARY},
        enabled=True,
    )
    db_session.add(policy)
    db_session.flush()
    return policy


def _eval_run(db_session, project, candidate, *, verdict, recommendation_id=None) -> EvalRun:
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=recommendation_id,
        lever="model_downshift",
        route_key=INCUMBENT,
        incumbent_model=INCUMBENT,
        candidate_model=candidate,
        status=RUN_COMPLETED,
        verdict=verdict,
        sample_count=30,
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_add_candidate_requires_completed_eval(db_session, provision):
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    with pytest.raises(routing.BanditCandidateError, match="no completed shadow eval"):
        routing.add_bandit_candidate(db_session, policy, CHALLENGER)


def test_add_candidate_safe_verdict_clears(db_session, provision):
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    run = _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_SAFE)

    routing.add_bandit_candidate(db_session, policy, CHALLENGER)
    entries = routing.bandit_candidate_entries(policy)
    assert [e["model"] for e in entries] == [CHALLENGER]
    assert entries[0]["eval_run_id"] == str(run.id)


def test_add_candidate_unsafe_verdict_blocked(db_session, provision):
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_UNSAFE)
    with pytest.raises(routing.BanditCandidateError, match="did not clear"):
        routing.add_bandit_candidate(db_session, policy, CHALLENGER)


def test_add_candidate_needs_human_requires_approved_change_request(db_session, provision):
    p, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"rec-{uuid.uuid4()}",
        type="model_downshift",
        lever="model_downshift",
        title="swap",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=INCUMBENT,
    )
    db_session.add(rec)
    db_session.flush()
    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_NEEDS_HUMAN, recommendation_id=rec.id)

    with pytest.raises(routing.BanditCandidateError, match="approve its"):
        routing.add_bandit_candidate(db_session, policy, CHALLENGER)

    user = db_session.scalar(select(User).where(User.auth_provider_subject == p["sub"]))
    db_session.add(
        ChangeRequest(
            organization_id=project.organization_id,
            project_id=project.id,
            recommendation_id=rec.id,
            lever="model_downshift",
            incumbent_model=INCUMBENT,
            candidate_model=CHALLENGER,
            status="approved",
            decided_by_user_id=user.id,
        )
    )
    db_session.flush()
    routing.add_bandit_candidate(db_session, policy, CHALLENGER)
    assert [e["model"] for e in routing.bandit_candidate_entries(policy)] == [CHALLENGER]


def test_add_candidate_rejects_duplicates_and_primary(db_session, provision):
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    with pytest.raises(routing.BanditCandidateError, match="already the policy's primary"):
        routing.add_bandit_candidate(db_session, policy, PRIMARY)
    with pytest.raises(routing.BanditCandidateError, match="different from the incumbent"):
        routing.add_bandit_candidate(db_session, policy, INCUMBENT)

    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_SAFE)
    routing.add_bandit_candidate(db_session, policy, CHALLENGER)
    with pytest.raises(routing.BanditCandidateError, match="already in the bandit"):
        routing.add_bandit_candidate(db_session, policy, CHALLENGER)


def test_remove_candidate(db_session, provision):
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_SAFE)
    routing.add_bandit_candidate(db_session, policy, CHALLENGER)

    assert routing.remove_bandit_candidate(db_session, policy, CHALLENGER) is True
    assert routing.bandit_candidate_entries(policy) == []
    assert routing.remove_bandit_candidate(db_session, policy, CHALLENGER) is False


# --- drift: surgical candidate removal ---------------------------------------------


def _arm_usage(db_session, project, *, candidate, arm, ok, count):
    model = INCUMBENT if arm == "control" else candidate
    for _ in range(count):
        db_session.add(
            UsageEvent(
                project_id=project.id,
                organization_id=project.organization_id,
                provider="openai",
                model=model,
                operation="chat_completion",
                request_type="chat_completion",
                feature="proxy",
                environment="production",
                input_tokens=1000,
                output_tokens=500,
                cached_input_tokens=0,
                total_tokens=1500,
                cost_usd=Decimal("0.001"),
                cost_source="catalog",
                pricing_status="priced",
                currency="USD",
                status="success",
                success=True,
                event_metadata={
                    "proxy": True,
                    "holdback": True,
                    "arm": arm,
                    "experiment_from": INCUMBENT,
                    "experiment_to": candidate,
                    "quality_ok": ok,
                },
                occurred_at=datetime.now(UTC),
            )
        )
    db_session.flush()


def test_drift_removes_regressed_bandit_candidate_only(db_session, provision, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    _, project = _sync_project(db_session, provision)
    policy = _sync_policy(db_session, project)
    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_SAFE)
    routing.add_bandit_candidate(db_session, policy, CHALLENGER)

    # Primary pair healthy; challenger pair fully degraded.
    _arm_usage(db_session, project, candidate=PRIMARY, arm="control", ok=True, count=15)
    _arm_usage(db_session, project, candidate=PRIMARY, arm="treatment", ok=True, count=15)
    _arm_usage(db_session, project, candidate=CHALLENGER, arm="control", ok=True, count=15)
    _arm_usage(db_session, project, candidate=CHALLENGER, arm="treatment", ok=False, count=15)
    db_session.commit()

    rolled = drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))

    db_session.refresh(policy)
    assert policy.enabled is True  # the route survives
    assert routing.bandit_candidate_entries(policy) == []  # the candidate does not
    assert any(r["trigger"] == "quality" and "bandit" in r["route"] for r in rolled)
    action = db_session.scalar(
        select(RecommendationAction).where(
            RecommendationAction.project_id == project.id,
            RecommendationAction.action_type == "bandit_candidate_removed",
        )
    )
    assert action is not None and action.source == "system"


# --- endpoints ----------------------------------------------------------------------


def test_endpoints_add_list_remove(client, db_session, provision):
    p, project = _sync_project(db_session, provision, plan="performance")
    policy = _sync_policy(db_session, project)
    _eval_run(db_session, project, CHALLENGER, verdict=VERDICT_SAFE)
    db_session.commit()

    headers = {"Authorization": f"Bearer {p['sub']}"}
    params = {"project_id": str(project.id)}

    # Uncleared model is rejected with the reason.
    blocked = client.post(
        f"/v1/engine/routes/{policy.id}/bandit-candidates",
        headers=headers,
        params=params,
        json={"candidate_model": "gpt-uncleared"},
    )
    assert blocked.status_code == 409
    assert "no completed shadow eval" in blocked.json()["detail"]

    added = client.post(
        f"/v1/engine/routes/{policy.id}/bandit-candidates",
        headers=headers,
        params=params,
        json={"candidate_model": CHALLENGER},
    )
    assert added.status_code == 200
    assert [e["model"] for e in added.json()["bandit_candidates"]] == [CHALLENGER]

    listed = client.get(f"/v1/engine/routes/{policy.id}/bandit-candidates", headers=headers, params=params)
    assert listed.status_code == 200
    assert listed.json()["primary_candidate"] == PRIMARY

    removed = client.delete(
        f"/v1/engine/routes/{policy.id}/bandit-candidates/{CHALLENGER}", headers=headers, params=params
    )
    assert removed.status_code == 200
    assert removed.json()["bandit_candidates"] == []


# --- end to end through the proxy ---------------------------------------------------


def _mock_openai(monkeypatch, seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["model"] = payload.get("model")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.anyio
async def test_active_bandit_routes_and_persists_decision(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    monkeypatch.setattr(settings, "bandit_routing_mode", "active")
    ws = await async_provision(sub="auth0|bandit-e2e", email="bandit-e2e@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    async_db_session.add(
        ModelPrice(
            model_key=CHALLENGER,
            provider="openai",
            currency="USD",
            input_cost_per_token=Decimal("0.00000015"),
            output_cost_per_token=Decimal("0.0000006"),
            source="catalog",
            effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    async_db_session.add(_policy(project, params_extra=_bandit_params()))
    await async_db_session.flush()
    await _seed_winning_challenger(async_db_session, project)

    seen: dict = {}
    _mock_openai(monkeypatch, seen)

    resp = await async_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {ws['api_key']}",
            "X-Varsten-Metadata": json.dumps(
                {"task_type": "classification.intent", "task_confidence": 0.95, "risk_level": "low"}
            ),
        },
        json={"model": INCUMBENT, "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200
    # The bandit's exploit choice went upstream, not the static primary.
    assert seen["model"] == CHALLENGER
    assert resp.headers.get("X-Varsten-Routed") == f"{INCUMBENT}->{CHALLENGER}"

    # The decision and its bandit trace are persisted: real learning material.
    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == project.id)
    )
    assert decision is not None
    assert decision.model_chosen == CHALLENGER
    assert decision.optimization_applied is True
    trace = [e for e in decision.event_metadata.get("runtime_trace", []) if e.get("stage") == "bandit_routing"]
    assert len(trace) == 1
    assert trace[0]["enforced"] is True
    assert trace[0]["detail"]["chosen_model"] == CHALLENGER
