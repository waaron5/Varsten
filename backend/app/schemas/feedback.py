import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import FEEDBACK_OUTCOMES


class FeedbackCreate(BaseModel):
    """Outcome feedback for a prior Varsten request. At least one of request_id or
    usage_event_id must be supplied so the signal can be tied to a decision."""

    request_id: str | None = Field(default=None, max_length=128)
    usage_event_id: uuid.UUID | None = None
    outcome: str
    quality_score: Decimal | None = Field(default=None, ge=0, le=1)
    failure_mode: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> "FeedbackCreate":
        if self.outcome not in FEEDBACK_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(FEEDBACK_OUTCOMES)}")
        if self.request_id is None and self.usage_event_id is None:
            raise ValueError("one of request_id or usage_event_id is required")
        return self


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    usage_event_id: uuid.UUID | None
    decision_event_id: uuid.UUID | None
    request_id: str | None
    outcome: str
    quality_score: Decimal | None
    failure_mode: str | None
    source: str
