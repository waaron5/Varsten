import uuid

from pydantic import BaseModel, Field

from app.schemas.organization import OrganizationOut


class AuthSyncRequest(BaseModel):
    # Identity comes from the validated token (sub). These are profile display
    # fields the frontend reads from the Auth0 session; used only when the token
    # itself does not carry namespaced email/name claims.
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=255)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    organizations: list[OrganizationOut]
