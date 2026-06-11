import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OperatorProvisionRequest(BaseModel):
    customer_email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    organization_name: str = Field(min_length=1, max_length=255)
    project_name: str = Field(min_length=1, max_length=255)
    api_key_name: str = Field(min_length=1, max_length=255)


class OperatorProvisionResponse(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    api_key_id: uuid.UUID
    api_key_prefix: str
    plaintext_api_key: str


class OperatorValidationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    organization_id: uuid.UUID
    project_name: str
    window_hours: int
    window_start: datetime
    window_end: datetime
    request_count: int
    p95_latency_ms: int | None
    saved_usd: Decimal | None
    fail_open_status: str
    follow_up_draft: str
