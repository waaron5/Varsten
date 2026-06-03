import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    proxy_bypass_enabled: bool
    created_at: datetime
    updated_at: datetime


class ProjectProxyConfigUpdate(BaseModel):
    bypass_enabled: bool
