"""Deterministic prefix-restructuring proposals (D1 follow-through).

The pure alignment finds the stable head/tail around a volatile middle and
only proposes when restructuring actually changes the outcome; the wired
recommendation carries the proposal as structure metrics on ``details`` and a
concrete sentence in the description — never prompt text, because
recommendations are a metadata-only store.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.engine.prefix_analysis import analyze_prefix_structure, propose_prefix_restructure
from app.models import ModelPrice, Project, Recommendation, ReplaySample, RequestDecisionEvent, UsageEvent
from app.recommendations import _add_prompt_cache_recommendation
from app.savings import month_start

MODEL = "gpt-4o-mini"
FEATURE = "support_agent"

HEAD = "You are the support policy engine. Apply the following rules in order. " * 9  # ~640 chars
TAIL = " Always answer in English, cite the rule you applied, and never guess. " * 13  # ~930 chars
SECRET = "VOLATILE-CUSTOMER-FRAGMENT"


def _texts(n: int = 8) -> list[str]:
    # The middle must vary at its FIRST and LAST characters (i at both edges),
    # or the common-prefix/suffix alignment would correctly extend into it.
    return [f"{HEAD}{i}-{SECRET} now=2026-07-04T00:0{i}{TAIL}" for i in range(n)]


# --- pure alignment -----------------------------------------------------------------


def test_volatile_middle_is_located_exactly():
    proposal = analyze_prefix_structure(_texts())
    assert proposal is not None
    assert proposal.stable_prefix_chars == len(HEAD)
    assert proposal.volatile_span_offset == len(HEAD)
    assert proposal.stable_suffix_chars == len(TAIL)
    assert proposal.sample_count == 8
    # Head is under half the prompt, but head+tail clears the floor.
    assert proposal.stable_prefix_share < 0.5
    assert proposal.projected_stable_share > 0.9


def test_identical_prompts_need_no_restructuring():
    assert analyze_prefix_structure(["same text"] * 10) is None


def test_too_few_samples_is_anecdote_not_structure():
    assert analyze_prefix_structure(_texts(4)) is None


def test_already_stable_head_is_not_proposed():
    # The volatile part is a tiny tail; the head is already ~99% of the prompt.
    texts = [f"{HEAD * 3} v={i}" for i in range(8)]
    assert analyze_prefix_structure(texts) is None


def test_fully_volatile_prompt_gains_nothing():
    texts = [f"totally different every time {i} " * (i + 1) for i in range(8)]
    assert analyze_prefix_structure(texts) is None


def test_volatile_span_lengths_never_negative():
    # One sample is exactly head+tail: the volatile span's minimum is zero and
    # the tail must not double-count into the head.
    texts = [f"{HEAD}{TAIL}"] + [f"{HEAD}x{i}{TAIL}" for i in range(7)]
    proposal = analyze_prefix_structure(texts)
    assert proposal is not None
    assert proposal.volatile_span_min_chars == 0
    assert proposal.volatile_span_max_chars >= 2


# --- wired into detection -------------------------------------------------------------


def _seed_route(db_session, project):
    db_session.add(
        ModelPrice(
            model_key=MODEL,
            provider="openai",
            currency="USD",
            input_cost_per_token=Decimal("0.00000015"),
            cache_read_input_token_cost=Decimal("0.000000075"),
            output_cost_per_token=Decimal("0.0000006"),
            source="catalog",
            effective_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    for _ in range(30):
        db_session.add(
            UsageEvent(
                project_id=project.id,
                organization_id=project.organization_id,
                provider="openai",
                model=MODEL,
                operation="chat_completion",
                request_type="chat_completion",
                feature=FEATURE,
                environment="production",
                input_tokens=3000,
                cached_input_tokens=0,
                output_tokens=100,
                total_tokens=3100,
                cost_usd=Decimal("0.001"),
                cost_source="catalog",
                pricing_status="priced",
                currency="USD",
                status="success",
                success=True,
                occurred_at=datetime.now(UTC),
            )
        )
    for i in range(25):  # every request a different fingerprint: the prefix churns
        db_session.add(
            RequestDecisionEvent(
                organization_id=project.organization_id,
                project_id=project.id,
                request_id=f"req_prop_{i}",
                provider_requested="openai",
                model_requested=MODEL,
                decision_type="passthrough",
                route_key=FEATURE,
                prefix_hash=f"hash{i}",
            )
        )
    db_session.flush()


def _seed_corpus(db_session, project, texts):
    for i, text in enumerate(texts):
        db_session.add(
            ReplaySample(
                organization_id=project.organization_id,
                project_id=project.id,
                route_key=MODEL,
                source="traffic",
                incumbent_model=MODEL,
                request_messages=[
                    {"role": "system", "content": text},
                    {"role": "user", "content": f"question {i}"},
                ],
                request_params={},
                expires_at=None,
            )
        )
    db_session.flush()


def test_restructure_recommendation_carries_the_proposal(db_session, provision):
    p = provision()
    project = db_session.get(Project, uuid.UUID(p["project_id"]))
    _seed_route(db_session, project)
    _seed_corpus(db_session, project, _texts())
    db_session.commit()

    _add_prompt_cache_recommendation(db_session, project, month_start(datetime.now(UTC)), datetime.now(UTC))
    db_session.flush()

    rec = db_session.scalar(
        select(Recommendation).where(
            Recommendation.project_id == project.id,
            Recommendation.type == "prompt_prefix_restructure",
        )
    )
    assert rec is not None
    assert rec.details is not None
    proposal = rec.details["prefix_restructure_proposal"]
    assert proposal["stable_prefix_chars"] == len(HEAD)
    assert proposal["volatile_span_offset"] == len(HEAD)
    assert proposal["projected_stable_share"] > 0.9
    assert f"offset {len(HEAD):,}" in rec.description

    # Content rules: the persisted proposal is structure only — no fragment of
    # the captured prompts may appear anywhere on the recommendation.
    blob = json.dumps({"details": rec.details, "description": rec.description, "title": rec.title})
    assert SECRET not in blob
    assert HEAD[:40] not in blob


def test_direct_proposal_helper_is_fail_open(db_session, provision):
    p = provision()
    project = db_session.get(Project, uuid.UUID(p["project_id"]))
    # No corpus at all: the helper degrades to None, never raises.
    assert propose_prefix_restructure(db_session, project, MODEL) is None
