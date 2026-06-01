import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class UsageEventCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    external_user_id: str | None = Field(default=None, max_length=255)
    workflow: str | None = Field(default=None, max_length=255)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=1, max_length=8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    model: str
    operation: str
    external_user_id: str | None
    workflow: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    currency: str
    # ORM attribute is event_metadata (column "metadata"); expose it as "metadata".
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("event_metadata", "metadata"),
    )
    received_at: datetime


class UsageEventPage(BaseModel):
    """A page of usage events. has_more avoids a COUNT(*) on the hot table:
    the query fetches limit + 1 rows and trims the extra."""

    items: list[UsageEventOut]
    limit: int
    offset: int
    has_more: bool
