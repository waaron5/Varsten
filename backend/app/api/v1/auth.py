from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import billing_lifecycle
from app.api.deps import get_token_claims, require_user
from app.db.session import get_db
from app.models import PLAN_FREE, SUBSCRIPTION_ACTIVE, Organization, OrgMembership, User
from app.provisioning import provision_new_organization
from app.schemas import AuthSyncRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Namespaced custom claims, if the tenant is configured to add them to the access
# token (via an Auth0 Action). Trusted over the request body when present.
EMAIL_CLAIM = "https://varsten.app/email"
NAME_CLAIM = "https://varsten.app/name"


def _user_out(user: User, db: Session) -> UserOut:
    orgs = db.scalars(
        select(Organization)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user.id)
        .order_by(Organization.created_at.asc())
    ).all()
    return UserOut.model_validate(
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "organizations": list(orgs),
        }
    )


@router.post("/sync", response_model=UserOut)
def sync_user(
    payload: AuthSyncRequest,
    claims: dict = Depends(get_token_claims),
    db: Session = Depends(get_db),
) -> UserOut:
    """Provision or refresh the signed-in user from their Auth0 identity.

    The token's `sub` is the identity. A brand-new user is bootstrapped with a
    personal organization so they have somewhere to create projects. Identity is
    never linked by email (that would allow account takeover via a chosen email).
    """
    sub = claims["sub"]
    email = claims.get(EMAIL_CLAIM) or payload.email
    name = claims.get(NAME_CLAIM) or payload.name

    user = db.scalar(select(User).where(User.auth_provider_subject == sub))
    try:
        if user is None:
            user = db.scalar(
                select(User).where(
                    func.lower(User.email) == email.lower(),
                    User.auth_provider_subject.is_(None),
                )
            )
            if user is None:
                user = User(email=email, name=name, auth_provider_subject=sub)
                db.add(user)
                db.flush()
                # New signup: a Pro-trialing org with a ready-to-use default
                # project, so the 14-day trial is live and onboarding has somewhere to
                # mint an API key without asking the user to create a project first.
                provision_new_organization(
                    db,
                    name=_default_org_name(email),
                    owner_user_id=user.id,
                    start_trial=payload.onboarding_intent != "observe",
                )
            else:
                user.auth_provider_subject = sub
                user.name = name or user.name
        else:
            user.email = email
            user.name = name
        _apply_onboarding_intent(db, user, payload.onboarding_intent)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already associated with another account",
        ) from None

    db.refresh(user)
    return _user_out(user, db)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user), db: Session = Depends(get_db)) -> UserOut:
    return _user_out(user, db)


def _default_org_name(email: str) -> str:
    local = email.split("@", 1)[0] if "@" in email else email
    return f"{local}'s workspace"


def _apply_onboarding_intent(db: Session, user: User, intent: str | None) -> None:
    if intent != "trial":
        return
    org = _primary_org_for_user(db, user)
    if org is None:
        return
    if not _can_start_self_serve_trial(org):
        return
    billing_lifecycle.start_trial(org)


def _primary_org_for_user(db: Session, user: User) -> Organization | None:
    return db.scalar(
        select(Organization)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .limit(1)
    )


def _can_start_self_serve_trial(org: Organization) -> bool:
    return (
        org.plan_tier == PLAN_FREE
        and org.subscription_status == SUBSCRIPTION_ACTIVE
        and org.trial_started_at is None
        and org.stripe_subscription_id is None
        and org.payment_method_ready_at is None
    )
