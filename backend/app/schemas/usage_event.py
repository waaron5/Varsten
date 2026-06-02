import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class UsageEventCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    request_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("request_type", "operation"),
        max_length=64,
    )
    feature: str | None = Field(
        default=None,
        validation_alias=AliasChoices("feature", "workflow"),
        max_length=255,
    )
    customer_id: str | None = Field(default=None, max_length=255)
    user_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("user_id", "external_user_id"),
        max_length=255,
    )
    team: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=64)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    # Subset of input_tokens served from a provider prompt cache.
    cached_input_tokens: int = Field(default=0, ge=0)
    # Reasoning/thinking tokens, for analytics. Not billed separately; providers
    # already fold them into output_tokens.
    reasoning_tokens: int = Field(default=0, ge=0)
    # Optional now: Varsten derives cost from the catalog when the model is known.
    # Sent cost is kept as a cross-check and used only when the model is unpriced.
    cost_usd: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=1, max_length=8)
    # When the call actually happened on the client; defaults to receipt time.
    occurred_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("occurred_at", "event_timestamp"),
    )
    # Caller-scoped key so retries do not double-count. Unique per project.
    idempotency_key: str | None = Field(default=None, max_length=255)
    status: Literal["success", "error"] = "success"
    success: bool | None = None
    error_code: str | None = Field(default=None, max_length=128)
    latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_compat_defaults(self) -> "UsageEventCreate":
        if self.request_type is None:
            self.request_type = "unknown"
        if self.environment is None:
            raw_environment = self.metadata.get("environment")
            self.environment = (
                str(raw_environment)
                if raw_environment is not None and str(raw_environment).strip()
                else "unknown"
            )
        if self.team is None and self.metadata.get("team") is not None:
            self.team = str(self.metadata["team"])
        if self.department is None and self.metadata.get("department") is not None:
            self.department = str(self.metadata["department"])
        if self.customer_id is None and self.metadata.get("customer_id") is not None:
            self.customer_id = str(self.metadata["customer_id"])
        if self.success is None:
            self.success = self.status != "error"
        return self

    @property
    def operation(self) -> str:
        return self.request_type or "unknown"

    @property
    def workflow(self) -> str | None:
        return self.feature

    @property
    def external_user_id(self) -> str | None:
        return self.user_id

    @property
    def event_timestamp(self) -> datetime | None:
        return self.occurred_at


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    api_key_id: uuid.UUID | None
    provider: str
    model: str
    operation: str
    external_user_id: str | None
    workflow: str | None
    request_type: str | None
    feature: str | None
    customer_id: str | None
    user_id: str | None
    team: str | None
    department: str | None
    environment: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: Decimal | None
    reported_cost_usd: Decimal | None
    cost_source: str
    pricing_status: str
    price_version_id: uuid.UUID | None
    currency: str
    status: str
    success: bool
    error_code: str | None
    latency_ms: int | None
    # ORM attribute is event_metadata (column "metadata"); expose it as "metadata".
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("event_metadata", "metadata"),
    )
    event_timestamp: datetime | None
    occurred_at: datetime | None
    received_at: datetime


class UsageEventPage(BaseModel):
    """A page of usage events. has_more avoids a COUNT(*) on the hot table:
    the query fetches limit + 1 rows and trims the extra."""

    items: list[UsageEventOut]
    limit: int
    offset: int
    has_more: bool
