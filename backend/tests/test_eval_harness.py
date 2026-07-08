"""Eval / replay harness: scoring tiers, the shadow-run verdict logic, the apply
gate, and the capture tap. Model calls (replay, judge) are injected stubs so the
runner's aggregation and verdict are tested with no network."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.eval import capture as eval_capture
from app.eval import scoring
from app.eval.runner import run_eval
from app.models import EvalRun, Project, Recommendation, ReplaySample, UsageEvent
from app.models.eval import (
    RUN_COMPLETED,
    RUN_PENDING,
    SOURCE_GOLDEN,
    SOURCE_TRAFFIC,
    VERDICT_INSUFFICIENT,
    VERDICT_NEEDS_HUMAN,
    VERDICT_SAFE,
    VERDICT_UNSAFE,
)


def _completion(text: str, ptok: int = 10, ctok: int = 5) -> dict:
    return {
        "model": "gpt-4o-mini",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok},
    }


def _project(db, provision) -> Project:
    ws = provision(sub="auth0|eval", email="eval@example.com", plan="performance")
    return db.get(Project, uuid.UUID(ws["project_id"]))


def _mk_rec(db, project, **over) -> Recommendation:
    fields = {
        "organization_id": project.organization_id,
        "project_id": project.id,
        "dedupe_key": f"k-{uuid.uuid4()}",
        "type": "model_downshift",
        "lever": "model_downshift",
        "title": "Evaluate gpt-4o-mini for support",
        "description": "x",
        "risk_level": "medium",
        "confidence": "medium",
        "related_model": "gpt-4o",
        "related_provider": "openai",
        "monthly_request_volume": 1000,
    }
    fields.update(over)
    rec = Recommendation(**fields)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _mk_sample(db, project, *, incumbent_text, source=SOURCE_TRAFFIC, route="gpt-4o", expected=None):
    s = ReplaySample(
        organization_id=project.organization_id,
        project_id=project.id,
        route_key=route,
        source=source,
        incumbent_model=route,
        request_messages=[{"role": "user", "content": "classify this"}],
        request_params={},
        incumbent_response=_completion(incumbent_text),
        expected_output=expected,
        input_tokens=10,
        output_tokens=5,
        expires_at=None,
    )
    db.add(s)
    db.commit()
    return s


def _run(db, rec, project, candidate, replay_fn, judge_fn=None) -> EvalRun:
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=rec.id,
        lever="model_downshift",
        route_key="gpt-4o",
        incumbent_model="gpt-4o",
        candidate_model=candidate,
        status=RUN_PENDING,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    async def default_judge(prompt, inc, cand, key):
        return "tie", ""

    asyncio.run(run_eval(db, run, key="sk-test", replay_fn=replay_fn, judge_fn=judge_fn or default_judge))
    db.refresh(run)
    return run


# --- scoring units (no DB) ------------------------------------------------------


def test_score_golden_exact_match_is_parity():
    s = ReplaySample(source=SOURCE_GOLDEN, expected_output="Spam", request_params={})
    scorer, score, ok = scoring.score_sample(s, "", "spam")
    assert scorer == scoring.SCORER_GOLDEN and ok is True and score == Decimal("0")


def test_score_golden_mismatch_is_loss():
    s = ReplaySample(source=SOURCE_GOLDEN, expected_output="spam", request_params={})
    _, score, ok = scoring.score_sample(s, "", "ham")
    assert ok is False and score == Decimal("-1")


def test_score_json_structural_equality():
    s = ReplaySample(source=SOURCE_TRAFFIC, request_params={})
    _, score, ok = scoring.score_sample(s, '{"label": "a"}', '{"label":"a"}')
    assert ok is True and score == Decimal("0")
    _, score2, ok2 = scoring.score_sample(s, '{"label": "a"}', '{"label":"b"}')
    assert ok2 is False and score2 == Decimal("-1")


def test_score_subjective_returns_none_for_judge():
    s = ReplaySample(source=SOURCE_TRAFFIC, request_params={})
    long = "This is a long open-ended generated answer that has no objective check."
    _, _, ok = scoring.score_sample(s, long, "Some other long prose answer entirely.")
    assert ok is None


def test_mean_ci_basic():
    mean, lo, hi = scoring.mean_ci([Decimal("0"), Decimal("0"), Decimal("-1"), Decimal("0")])
    assert lo <= mean <= hi


# --- runner verdicts ------------------------------------------------------------


def test_objective_parity_yields_safe(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 3)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    for _ in range(4):
        _mk_sample(db_session, project, incumbent_text='{"label":"spam"}')

    async def replay_match(messages, params, model, key):
        return _completion('{"label":"spam"}')

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_match)
    assert run.status == RUN_COMPLETED
    assert run.verdict == VERDICT_SAFE
    assert run.scorer_type == "objective"
    assert run.sample_count == 4 and run.loss_count == 0


def test_objective_degradation_yields_unsafe(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 3)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    for _ in range(4):
        _mk_sample(db_session, project, incumbent_text='{"label":"spam"}')

    async def replay_wrong(messages, params, model, key):
        return _completion('{"label":"ham"}')

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_wrong)
    assert run.verdict == VERDICT_UNSAFE and run.loss_count == 4


def test_subjective_route_needs_human_never_auto(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 3)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    long = "A long open ended explanation that cannot be scored objectively at all."
    for _ in range(4):
        _mk_sample(db_session, project, incumbent_text=long)

    async def replay_prose(messages, params, model, key):
        return _completion("A different but plausible long explanation of the topic.")

    async def judge_candidate_wins(prompt, inc, cand, key):
        return "candidate", ""

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_prose, judge_candidate_wins)
    # Even when the judge likes the candidate, a subjective route can only be
    # approved by a human, never auto-applied.
    assert run.verdict == VERDICT_NEEDS_HUMAN and run.scorer_type == "judge"


def test_too_few_samples_is_insufficient(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 20)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    _mk_sample(db_session, project, incumbent_text='{"label":"spam"}')

    async def replay_match(messages, params, model, key):
        return _completion('{"label":"spam"}')

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_match)
    assert run.verdict == VERDICT_INSUFFICIENT


def test_golden_samples_scored_first(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 2)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    _mk_sample(db_session, project, source=SOURCE_GOLDEN, incumbent_text="", expected="yes")
    _mk_sample(db_session, project, source=SOURCE_GOLDEN, incumbent_text="", expected="yes")

    async def replay_yes(messages, params, model, key):
        return _completion("yes")

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_yes)
    assert run.scorer_type == "golden" and run.verdict == VERDICT_SAFE


def test_eval_replay_overhead_is_metered(client, provision, db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 1)
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    _mk_sample(db_session, project, source=SOURCE_GOLDEN, incumbent_text="", expected="yes")

    async def replay_yes(messages, params, model, key):
        return _completion("yes", ptok=11, ctok=3)

    run = _run(db_session, rec, project, "gpt-4o-mini", replay_yes)

    overhead = list(
        db_session.scalars(
            select(UsageEvent).where(
                UsageEvent.project_id == project.id,
                UsageEvent.event_metadata["overhead"].astext == "eval_replay",
            )
        )
    )
    assert run.status == RUN_COMPLETED
    assert len(overhead) == 1
    assert overhead[0].source == "overhead"
    assert overhead[0].operation == "eval_replay"
    assert overhead[0].input_tokens == 11
    assert overhead[0].output_tokens == 3


# --- apply gate -----------------------------------------------------------------


def test_apply_blocked_without_passing_eval(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project)
    resp = client.patch(
        f"/v1/recommendations/{rec.id}",
        headers={"Authorization": "Bearer auth0|eval"},
        json={"status": "applied"},
    )
    assert resp.status_code == 409
    assert "shadow evaluation" in resp.json()["detail"].lower()


def test_apply_allowed_with_safe_run_uses_measured_savings(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project, estimated_monthly_savings_usd=Decimal("100"))
    db_session.add(
        EvalRun(
            organization_id=project.organization_id,
            project_id=project.id,
            recommendation_id=rec.id,
            lever="model_downshift",
            route_key="gpt-4o",
            incumbent_model="gpt-4o",
            candidate_model="gpt-4o-mini",
            status=RUN_COMPLETED,
            verdict=VERDICT_SAFE,
            cost_delta_usd=Decimal("250.00"),
        )
    )
    db_session.commit()

    resp = client.patch(
        f"/v1/recommendations/{rec.id}",
        headers={"Authorization": "Bearer auth0|eval"},
        json={"status": "applied"},
    )
    assert resp.status_code == 200
    db_session.refresh(rec)
    assert rec.status == "applied"
    assert rec.measurement_method == "replay_measured"
    assert rec.estimated_monthly_savings_usd == Decimal("250.00")


def test_non_gated_lever_applies_without_eval(client, provision, db_session):
    project = _project(db_session, provision)
    rec = _mk_rec(db_session, project, type="semantic_cache", lever="semantic_cache", related_model=None)
    resp = client.patch(
        f"/v1/recommendations/{rec.id}",
        headers={"Authorization": "Bearer auth0|eval"},
        json={"status": "applied"},
    )
    assert resp.status_code == 200


# --- capture tap ----------------------------------------------------------------


@pytest.mark.anyio
async def test_capture_respects_optin(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_capture_enabled", True)
    monkeypatch.setattr(settings, "eval_sample_rate", 1.0)
    ws = await async_provision(sub="auth0|cap1", email="cap1@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))

    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    # Opted out: nothing captured.
    project.eval_capture_enabled = False
    await async_db_session.flush()
    await eval_capture.capture_sample(
        async_db_session,
        project,
        body=body,
        response_payload=_completion("hello"),
        model="gpt-4o",
        input_tokens=10,
        output_tokens=2,
    )
    assert await async_db_session.scalar(select(ReplaySample).where(ReplaySample.project_id == project.id)) is None

    # Opted in: captured with a TTL.
    project.eval_capture_enabled = True
    await async_db_session.flush()
    await eval_capture.capture_sample(
        async_db_session,
        project,
        body=body,
        response_payload=_completion("hello"),
        model="gpt-4o",
        input_tokens=10,
        output_tokens=2,
    )
    sample = await async_db_session.scalar(select(ReplaySample).where(ReplaySample.project_id == project.id))
    assert sample is not None and sample.source == SOURCE_TRAFFIC and sample.expires_at is not None


@pytest.mark.anyio
async def test_capture_enforces_route_cap(async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "eval_capture_enabled", True)
    monkeypatch.setattr(settings, "eval_sample_rate", 1.0)
    monkeypatch.setattr(settings, "eval_max_samples_per_route", 3)
    ws = await async_provision(sub="auth0|cap2", email="cap2@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    project.eval_capture_enabled = True
    await async_db_session.flush()

    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    for _ in range(6):
        await eval_capture.capture_sample(
            async_db_session,
            project,
            body=body,
            response_payload=_completion("hi"),
            model="gpt-4o",
            input_tokens=10,
            output_tokens=2,
        )
    total = len(
        (await async_db_session.scalars(select(ReplaySample).where(ReplaySample.project_id == project.id))).all()
    )
    assert total == 3


# --- golden upload + capture config API ----------------------------------------


def test_golden_upload_and_capture_config(client, provision, db_session):
    ws = provision(sub="auth0|eval2", email="eval2@example.com")
    headers = {"Authorization": "Bearer auth0|eval2"}
    pid = ws["project_id"]

    resp = client.post(
        f"/v1/evals/golden?project_id={pid}",
        headers=headers,
        json={
            "samples": [{"route_key": "gpt-4o", "messages": [{"role": "user", "content": "q"}], "expected_output": "a"}]
        },
    )
    assert resp.status_code == 200 and resp.json()["created"] == 1

    resp = client.post(
        f"/v1/evals/capture-config?project_id={pid}",
        headers=headers,
        json={"eval_capture_enabled": True},
    )
    assert resp.status_code == 200 and resp.json()["eval_capture_enabled"] is True

    # The config read reflects both: capture is on and the golden sample is counted
    # under its route, so the UI can show corpus readiness.
    cfg = client.get(f"/v1/evals/config?project_id={pid}", headers=headers).json()
    assert cfg["eval_capture_enabled"] is True
    route = next(r for r in cfg["routes"] if r["route_key"] == "gpt-4o")
    assert route["golden_samples"] == 1
