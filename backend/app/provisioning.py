"""Create a fully-formed self-serve workspace.

A new workspace is an organization plus a default Production project. Without the
project a new user has nowhere to mint an API key, so onboarding dead-ends on its
first step. Creating it here (not asking the user) keeps the funnel uninterrupted.

By default the organization starts on a 14-day Optimize trial via the central
billing lifecycle, so the advertised trial is real the moment someone signs up.
"""

import uuid

from sqlalchemy.orm import Session

from app import billing_lifecycle
from app.models import Organization, OrgMembership, Project

DEFAULT_PROJECT_NAME = "Production"


def provision_new_organization(
    db: Session,
    *,
    name: str,
    owner_user_id: uuid.UUID | None = None,
    start_trial: bool = True,
) -> tuple[Organization, Project]:
    """Create an org (optionally on an Optimize trial), its owner membership, and a
    default Production project. Flushes so ids are available; the caller commits."""
    org = Organization(name=name)
    db.add(org)
    db.flush()  # assigns org.id before the trial transition / membership reference it
    if start_trial:
        billing_lifecycle.start_trial(org)
    if owner_user_id is not None:
        db.add(OrgMembership(organization_id=org.id, user_id=owner_user_id, role="owner"))
    project = Project(organization_id=org.id, name=DEFAULT_PROJECT_NAME)
    db.add(project)
    db.flush()
    return org, project
