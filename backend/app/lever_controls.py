"""Project-level runtime gates for automation levers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.levers import LEVER_DEFAULT_AUTOMATION
from app.models import LeverConfig

_DEFAULT_ENABLED = {lever: True for lever, _mode in LEVER_DEFAULT_AUTOMATION}


def lever_enabled(db: Session, project_id, lever: str | None) -> bool:
    """Return whether a lever is allowed for this project.

    Missing rows default to enabled so older projects keep their current behavior
    until the control-plane creates explicit LeverConfig rows.
    """
    if not lever:
        return True
    enabled = db.scalar(
        select(LeverConfig.enabled).where(
            LeverConfig.project_id == project_id,
            LeverConfig.lever == lever,
        )
    )
    if enabled is None:
        return _DEFAULT_ENABLED.get(lever, True)
    return bool(enabled)


async def lever_enabled_async(db: AsyncSession, project_id, lever: str | None) -> bool:
    if not lever:
        return True
    enabled = await db.scalar(
        select(LeverConfig.enabled).where(
            LeverConfig.project_id == project_id,
            LeverConfig.lever == lever,
        )
    )
    if enabled is None:
        return _DEFAULT_ENABLED.get(lever, True)
    return bool(enabled)
