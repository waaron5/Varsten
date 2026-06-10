import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recommendation_id: uuid.UUID | None
    lever: str
    route_key: str
    incumbent_model: str
    candidate_model: str
    status: str
    scorer_type: str | None
    sample_count: int
    win_count: int
    tie_count: int
    loss_count: int
    objective_pass_rate: Decimal | None
    score_delta: Decimal | None
    score_delta_ci_low: Decimal | None
    score_delta_ci_high: Decimal | None
    cost_delta_usd: Decimal | None
    verdict: str | None
    notes: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class EvalRunSummary(BaseModel):
    """Compact eval state attached to a recommendation card so the Engine UI can
    show the verdict and gate the apply without a second round-trip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    verdict: str | None
    scorer_type: str | None
    candidate_model: str
    sample_count: int
    objective_pass_rate: Decimal | None
    score_delta: Decimal | None
    score_delta_ci_low: Decimal | None
    score_delta_ci_high: Decimal | None
    cost_delta_usd: Decimal | None
    notes: str | None
    completed_at: datetime | None


class EvalSampleResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    replay_sample_id: uuid.UUID | None
    scorer: str
    objective_pass: bool | None
    judge_winner: str | None
    score: Decimal | None
    candidate_cost_usd: Decimal | None
    incumbent_cost_usd: Decimal | None
    notes: str | None


class EvalRunDetail(EvalRunOut):
    results: list[EvalSampleResultOut] = Field(default_factory=list)


class GoldenSampleIn(BaseModel):
    """A customer-asserted (prompt, expected answer) pair: the strongest scoring
    signal. route_key is the model the route runs on today."""

    route_key: str
    messages: list[dict]
    expected_output: str
    request_params: dict = Field(default_factory=dict)


class GoldenSampleBatchIn(BaseModel):
    samples: list[GoldenSampleIn]


class EvalCaptureConfigUpdate(BaseModel):
    eval_capture_enabled: bool
