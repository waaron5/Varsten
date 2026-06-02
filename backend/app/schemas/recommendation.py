import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


RecommendationStatus = Literal["open", "applied", "dismissed", "rolled_back"]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    type: str
    lever: str | None
    target_type: str | None
    target_key: str | None
    title: str
    description: str
    rationale: str | None
    estimated_monthly_savings_usd: Decimal | None
    monthly_request_volume: int | None
    quality_delta_percent: Decimal | None
    measurement_method: str
    risk_level: str
    confidence: str
    status: str
    related_provider: str | None
    related_model: str | None
    related_feature: str | None
    related_customer_id: str | None
    related_environment: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class RecommendationUpdate(BaseModel):
    status: RecommendationStatus
