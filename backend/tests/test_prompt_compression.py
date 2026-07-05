"""Learned prompt compression (slice D2).

The pipeline is generate (off-path, injectable generator, overhead-metered) ->
eval-gated -> approved -> canary+holdback execution. The hot path substitutes
the approved rewrite ONLY on an exact hash match of the evaluated original;
anything else passes through untouched — production prompts are never
compressed inline.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.engine import governance
from app.engine.compression import (
    CompressionGenerationError,
    extract_system_text,
    generate_compression_candidate,
    run_compression_eval,
    substitute_system_prompt,
    system_text_hash,
)
from app.eval.gate import EvalGateError, assert_appliable, is_gated
from app.levers import LEVER_PROMPT_COMPRESSION
from app.models import (
    EvalRun,
    Project,
    PromptCompression,
    ProxyPolicy,
    Recommendation,
    ReplaySample,
    RequestDecisionEvent,
    UsageEvent,
)
from app.models.eval import RUN_COMPLETED, VERDICT_NEEDS_HUMAN, VERDICT_SAFE
from app.proxy import compression as proxy_compression
from app.proxy import drift as drift_mod
from app.proxy import http_client
from app.savings import month_start

MODEL = "gpt-4o-mini"
# Long enough to clear compression_min_prompt_chars.
ORIGINAL = ("You are a meticulous support assistant. " * 40).strip()
COMPRESSED = "You are a meticulous support assistant."


@pytest.fixture(autouse=True)
def _clear_artifact_cache():
    proxy_compression.clear_artifact_cache()
    yield
    proxy_compression.clear_artifact_cache()


async def _fake_compress(system_prompt: str, key: str) -> tuple[str | None, int, int]:
    return COMPRESSED, 500, 60


def _project(db_session, provision, **kw) -> Project:
    p = provision(**kw)
    return db_session.get(Project, uuid.UUID(p["project_id"]))


def _seed_samples(db_session, project, *, count=3, system=ORIGINAL, expected="Spam"):
    for i in range(count):
        db_session.add(
            ReplaySample(
                organization_id=project.organization_id,
                project_id=project.id,
                route_key=MODEL,
                source="golden",
                incumbent_model=MODEL,
                request_messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"classify this {i}"},
                ],
                request_params={},
                incumbent_response=None,
                expected_output=expected,
                input_tokens=100,
                output_tokens=5,
                expires_at=None,
            )
        )
    db_session.flush()


# --- pure helpers ---------------------------------------------------------------


def test_extract_system_text():
    assert extract_system_text([{"role": "system", "content": "abc"}, {"role": "user", "content": "x"}]) == "abc"
    assert extract_system_text([{"role": "developer", "content": "abc"}]) == "abc"
    assert extract_system_text([{"role": "user", "content": "x"}]) is None
    assert extract_system_text([{"role": "system", "content": [{"type": "text", "text": "x"}]}]) is None
    assert extract_system_text(None) is None


def test_substitution_requires_exact_match():
    messages = [{"role": "system", "content": ORIGINAL}, {"role": "user", "content": "hi"}]
    out, applied = substitute_system_prompt(messages, system_text_hash(ORIGINAL), COMPRESSED)
    assert applied is True
    assert out[0]["content"] == COMPRESSED
    assert out[1] == messages[1]
    # One edited character: pass through untouched. Never compress the unproven.
    edited = [{"role": "system", "content": ORIGINAL + "!"}, {"role": "user", "content": "hi"}]
    out, applied = substitute_system_prompt(edited, system_text_hash(ORIGINAL), COMPRESSED)
    assert applied is False
    assert out == edited


# --- generation -----------------------------------------------------------------


@pytest.mark.anyio
async def test_generation_creates_artifact_recommendation_run_and_overhead(db_session, provision):
    project = _project(db_session, provision)
    _seed_samples(db_session, project)

    artifact = await generate_compression_candidate(
        db_session, project, MODEL, key="sk-test", compress_fn=_fake_compress, generator_label="injected:test"
    )

    assert artifact.original_system_hash == system_text_hash(ORIGINAL)
    assert artifact.compressed_system_prompt == COMPRESSED
    assert artifact.compressed_chars < artifact.original_chars

    rec = db_session.get(Recommendation, artifact.recommendation_id)
    assert rec is not None
    assert rec.lever == LEVER_PROMPT_COMPRESSION
    assert rec.status == "open"
    assert is_gated(rec)  # apply requires a shadow eval

    run = db_session.scalar(select(EvalRun).where(EvalRun.recommendation_id == rec.id))
    assert run is not None
    assert run.lever == LEVER_PROMPT_COMPRESSION
    assert run.incumbent_model == MODEL and run.candidate_model == MODEL

    # The generation LLM call was metered as overhead on the customer's ledger.
    overhead = db_session.scalar(
        select(UsageEvent).where(
            UsageEvent.project_id == project.id,
            UsageEvent.operation == "prompt_compression",
        )
    )
    assert overhead is not None
    assert overhead.event_metadata["overhead"] == "compression"
    assert overhead.input_tokens == 500 and overhead.output_tokens == 60


@pytest.mark.anyio
async def test_generation_rejects_insufficient_shrink(db_session, provision):
    project = _project(db_session, provision)
    _seed_samples(db_session, project)

    async def barely_shorter(prompt, key):
        return prompt[:-3], 10, 10  # nowhere near the 0.8 ratio bar

    with pytest.raises(CompressionGenerationError, match="compression bar"):
        await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=barely_shorter)
    assert db_session.scalar(select(PromptCompression)) is None


@pytest.mark.anyio
async def test_generation_rejects_short_prompts_and_empty_rewrites(db_session, provision):
    project = _project(db_session, provision)
    _seed_samples(db_session, project, system="short prompt")
    with pytest.raises(CompressionGenerationError, match="quality risk"):
        await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=_fake_compress)

    project2 = _project(db_session, provision, sub="auth0|c2", email="c2@example.com")
    _seed_samples(db_session, project2)

    async def no_rewrite(prompt, key):
        return None, 0, 0

    with pytest.raises(CompressionGenerationError, match="no usable rewrite"):
        await generate_compression_candidate(db_session, project2, MODEL, key="k", compress_fn=no_rewrite)


@pytest.mark.anyio
async def test_generation_requires_corpus(db_session, provision):
    project = _project(db_session, provision)
    with pytest.raises(CompressionGenerationError, match="no replay samples"):
        await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=_fake_compress)


# --- eval gating ------------------------------------------------------------------


@pytest.mark.anyio
async def test_eval_replays_with_substituted_prompt_and_skips_mismatches(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "eval_min_samples", 3)
    project = _project(db_session, provision)
    _seed_samples(db_session, project, count=3)
    # One sample with a different prompt: the eval must not score it.
    _seed_samples(db_session, project, count=1, system="a completely different system prompt " * 40)

    artifact = await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=_fake_compress)
    run = db_session.scalar(select(EvalRun).where(EvalRun.recommendation_id == artifact.recommendation_id))

    seen_prompts: list[str] = []

    async def replay_fn(messages, params, model, key):
        seen_prompts.append(messages[0]["content"])
        return {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Spam"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            "model": model,
        }

    await run_compression_eval(db_session, run, key="k", replay_fn=replay_fn)

    db_session.refresh(run)
    assert run.status == RUN_COMPLETED
    # Every scored replay read the compressed prompt, never the original.
    assert seen_prompts and all(p == COMPRESSED for p in seen_prompts)
    assert run.sample_count == 3  # the mismatched sample was skipped, not scored
    assert run.verdict == VERDICT_SAFE  # golden matches: objective parity
    # Measured input-token savings fall out of the same-model cost delta.
    assert run.cost_delta_usd is None or run.cost_delta_usd >= 0


def test_apply_is_blocked_without_eval(db_session, provision):
    project = _project(db_session, provision)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"pc-{uuid.uuid4()}",
        type=LEVER_PROMPT_COMPRESSION,
        lever=LEVER_PROMPT_COMPRESSION,
        title="compress",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=MODEL,
    )
    db_session.add(rec)
    db_session.flush()
    with pytest.raises(EvalGateError):
        assert_appliable(db_session, rec, automated=False)


def test_needs_human_verdict_proposes_change_request(db_session, provision):
    project = _project(db_session, provision)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"pc-{uuid.uuid4()}",
        type=LEVER_PROMPT_COMPRESSION,
        lever=LEVER_PROMPT_COMPRESSION,
        title="compress",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=MODEL,
    )
    db_session.add(rec)
    db_session.flush()
    run = EvalRun(
        organization_id=project.organization_id,
        project_id=project.id,
        recommendation_id=rec.id,
        lever=LEVER_PROMPT_COMPRESSION,
        route_key=MODEL,
        incumbent_model=MODEL,
        candidate_model=MODEL,
        status=RUN_COMPLETED,
        verdict=VERDICT_NEEDS_HUMAN,
        sample_count=30,
    )
    db_session.add(run)
    db_session.flush()

    change_request = governance.ensure_change_request(db_session, run)
    assert change_request is not None
    assert change_request.lever == LEVER_PROMPT_COMPRESSION


# --- activation --------------------------------------------------------------------


@pytest.mark.anyio
async def test_activation_conflicts_with_live_trim(db_session, provision):
    project = _project(db_session, provision)
    _seed_samples(db_session, project)
    artifact = await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=_fake_compress)
    rec = db_session.get(Recommendation, artifact.recommendation_id)

    db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever="token_trim",
            target_type="model",
            target_key=MODEL,
            enabled=True,
        )
    )
    db_session.flush()
    with pytest.raises(proxy_compression.TransformConflictError):
        proxy_compression.activate_compression_policy(db_session, project, rec)


@pytest.mark.anyio
async def test_activation_creates_policy_with_artifact(db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "canary_enabled", True)
    monkeypatch.setattr(settings, "canary_initial_percent", 10)
    project = _project(db_session, provision)
    _seed_samples(db_session, project)
    artifact = await generate_compression_candidate(db_session, project, MODEL, key="k", compress_fn=_fake_compress)
    rec = db_session.get(Recommendation, artifact.recommendation_id)

    policy = proxy_compression.activate_compression_policy(db_session, project, rec)
    db_session.flush()

    assert policy is not None
    assert policy.lever == LEVER_PROMPT_COMPRESSION
    assert policy.params["artifact_id"] == str(artifact.id)
    assert policy.rollout_percent == 10  # canary ramp applies
    assert policy.enabled is True

    proxy_compression.deactivate_compression_for_recommendation(db_session, rec)
    db_session.flush()
    db_session.refresh(policy)
    assert policy.enabled is False


def test_engine_update_compression_policy_pauses_and_caps_holdback(client, provision, db_session):
    p = provision()
    project = db_session.get(Project, uuid.UUID(p["project_id"]))
    artifact = PromptCompression(
        organization_id=project.organization_id,
        project_id=project.id,
        route_key=MODEL,
        model=MODEL,
        original_system_hash=system_text_hash(ORIGINAL),
        original_chars=len(ORIGINAL),
        compressed_system_prompt=COMPRESSED,
        compressed_chars=len(COMPRESSED),
        generator="injected:test",
    )
    db_session.add(artifact)
    db_session.flush()
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=LEVER_PROMPT_COMPRESSION,
        target_type="model",
        target_key=MODEL,
        enabled=True,
        holdback_percent=Decimal("0.05"),
        rollout_percent=50,
        params={"artifact_id": str(artifact.id)},
    )
    db_session.add(policy)
    db_session.commit()

    listed = client.get(
        "/v1/engine/compressions",
        headers={"Authorization": f"Bearer {p['token']}"},
        params={"project_id": str(project.id)},
    )
    assert listed.status_code == 200
    item = listed.json()[0]
    assert item["policy_id"] == str(policy.id)
    assert item["policy_enabled"] is True
    assert item["rollout_percent"] == 50

    resp = client.patch(
        f"/v1/engine/compressions/{policy.id}",
        headers={"Authorization": f"Bearer {p['token']}"},
        params={"project_id": str(project.id)},
        json={"enabled": False, "holdback_percent": "0.2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(policy.id)
    assert body["enabled"] is False
    assert Decimal(body["holdback_percent"]) == Decimal("0.2")
    assert body["rollout_percent"] == 50
    db_session.refresh(policy)
    assert policy.enabled is False and policy.holdback_percent == Decimal("0.2")

    bad = client.patch(
        f"/v1/engine/compressions/{policy.id}",
        headers={"Authorization": f"Bearer {p['token']}"},
        params={"project_id": str(project.id)},
        json={"holdback_percent": "0.9"},
    )
    assert bad.status_code == 422


# --- hot path ----------------------------------------------------------------------


def _mock_openai(monkeypatch, seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["messages"] = payload.get("messages")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55},
            },
        )

    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _low_risk_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Varsten-Metadata": json.dumps(
            {"task_type": "classification.intent", "task_confidence": 0.95, "risk_level": "low"}
        ),
    }


async def _seed_live_policy(async_db_session, project) -> PromptCompression:
    artifact = PromptCompression(
        organization_id=project.organization_id,
        project_id=project.id,
        route_key=MODEL,
        model=MODEL,
        original_system_hash=system_text_hash(ORIGINAL),
        original_chars=len(ORIGINAL),
        compressed_system_prompt=COMPRESSED,
        compressed_chars=len(COMPRESSED),
        generator="injected:test",
    )
    async_db_session.add(artifact)
    await async_db_session.flush()
    async_db_session.add(
        ProxyPolicy(
            organization_id=project.organization_id,
            project_id=project.id,
            lever=LEVER_PROMPT_COMPRESSION,
            target_type="model",
            target_key=MODEL,
            params={"artifact_id": str(artifact.id)},
            enabled=True,
            holdback_percent=Decimal("0"),  # deterministically treatment
        )
    )
    await async_db_session.flush()
    return artifact


@pytest.mark.anyio
async def test_proxy_substitutes_exact_match_and_records_evidence(
    async_client, async_provision, async_db_session, monkeypatch
):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|comp-e2e", email="comp-e2e@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    await _seed_live_policy(async_db_session, project)

    seen: dict = {}
    _mock_openai(monkeypatch, seen)

    resp = await async_client.post(
        "/v1/chat/completions",
        headers=_low_risk_headers(ws["api_key"]),
        json={
            "model": MODEL,
            "messages": [{"role": "system", "content": ORIGINAL}, {"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    # The upstream read the approved rewrite; the user turn is untouched.
    assert seen["messages"][0]["content"] == COMPRESSED
    assert seen["messages"][1]["content"] == "hi"

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == project.id)
    )
    assert decision is not None
    assert decision.optimization_applied is True
    assert decision.lever == LEVER_PROMPT_COMPRESSION
    trace = {e["stage"]: e for e in decision.event_metadata.get("runtime_trace", [])}
    assert trace["compression"]["action"] == "applied"
    parity = [e for e in decision.event_metadata["runtime_trace"] if e["stage"] == "planner_parity"]
    assert parity and parity[0]["action"] == "match"


@pytest.mark.anyio
async def test_proxy_passes_through_unmatched_prompt(async_client, async_provision, async_db_session, monkeypatch):
    monkeypatch.setattr(settings, "proxy_cache_enabled", False)
    ws = await async_provision(sub="auth0|comp-mismatch", email="comp-mismatch@example.com")
    project = await async_db_session.get(Project, uuid.UUID(ws["project_id"]))
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(project.id): "sk-test"})
    await _seed_live_policy(async_db_session, project)

    seen: dict = {}
    _mock_openai(monkeypatch, seen)

    edited = ORIGINAL + " Extra sentence the eval never saw."
    resp = await async_client.post(
        "/v1/chat/completions",
        headers=_low_risk_headers(ws["api_key"]),
        json={
            "model": MODEL,
            "messages": [{"role": "system", "content": edited}, {"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    # Never compress what was not evaluated: the edited prompt went up verbatim.
    assert seen["messages"][0]["content"] == edited

    decision = await async_db_session.scalar(
        select(RequestDecisionEvent).where(RequestDecisionEvent.project_id == project.id)
    )
    trace = {e["stage"]: e for e in decision.event_metadata.get("runtime_trace", [])}
    assert trace["compression"]["action"] == "noop"
    assert trace["compression"]["reason_code"] == "compression_prompt_mismatch"
    assert decision.optimization_applied is False


# --- drift rollback ---------------------------------------------------------------


def test_drift_rolls_back_compression_policy(db_session, provision, monkeypatch):
    monkeypatch.setattr(drift_mod, "MIN_ARM_SAMPLES", 10)
    project = _project(db_session, provision)
    rec = Recommendation(
        organization_id=project.organization_id,
        project_id=project.id,
        dedupe_key=f"pc-{uuid.uuid4()}",
        type=LEVER_PROMPT_COMPRESSION,
        lever=LEVER_PROMPT_COMPRESSION,
        title="compress",
        description="x",
        risk_level="medium",
        confidence="medium",
        related_model=MODEL,
    )
    db_session.add(rec)
    db_session.flush()
    policy = ProxyPolicy(
        organization_id=project.organization_id,
        project_id=project.id,
        lever=LEVER_PROMPT_COMPRESSION,
        target_type="model",
        target_key=MODEL,
        params={"artifact_id": str(uuid.uuid4())},
        enabled=True,
        holdback_percent=Decimal("0.1"),
        source_recommendation_id=rec.id,
    )
    db_session.add(policy)
    db_session.commit()

    # Same-model experiment pair: control healthy, compressed treatment degraded.
    for arm, ok in (("control", True), ("treatment", False)):
        for _ in range(15):
            db_session.add(
                UsageEvent(
                    project_id=project.id,
                    organization_id=project.organization_id,
                    provider="openai",
                    model=MODEL,
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
                        "experiment_from": MODEL,
                        "experiment_to": MODEL,
                        "quality_ok": ok,
                    },
                    occurred_at=datetime.now(UTC),
                )
            )
    db_session.commit()

    rolled = drift_mod.check_and_rollback_drift(db_session, project, month_start(datetime.now(UTC)))

    assert len(rolled) == 1
    assert rolled[0]["trigger"] == "quality"
    db_session.refresh(policy)
    db_session.refresh(rec)
    assert policy.enabled is False
    assert rec.status == "rolled_back"
