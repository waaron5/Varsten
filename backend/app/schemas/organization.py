import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    monthly_spend_budget_usd: Decimal | None = Field(default=None, ge=0)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    monthly_spend_budget_usd: Decimal | None
    created_at: datetime
    updated_at: datetime
