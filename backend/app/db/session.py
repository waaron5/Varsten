from collections.abc import AsyncGenerator, Generator
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Engines and session factories are created lazily, not at module import. Creating
# an engine eagerly imports the psycopg DBAPI (and loads its native libpq), so a
# module-level engine made importing *anything* in this package pull in the driver.
# Deferring it keeps import-only code paths (and the first-launch native-library
# verification cost) off the table until the database is actually used. The
# backward-compatible module attributes (engine, async_engine, SessionLocal,
# AsyncSessionLocal) are served lazily via __getattr__ below, so existing call
# sites keep working unchanged.


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The process-wide sync engine, created on first use.

    Pool sizing is explicit and config-driven so the per-instance connection draw is
    bounded and predictable when scaling horizontally (see Settings.db_pool_size)."""
    return create_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=settings.db_pool_pre_ping,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> "sessionmaker[Session]":
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    """The process-wide async engine, created on first use. The psycopg3 driver is
    both sync and async, so the same DATABASE_URL (postgresql+psycopg://...) drives
    it with no URL change. Shares the same config-driven pool sizing as the sync
    engine; the two pools are independent, so a single instance can hold up to
    (db_pool_size + db_max_overflow) connections in each."""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=settings.db_pool_pre_ping,
    )


@lru_cache(maxsize=1)
def get_async_session_factory() -> "async_sessionmaker[AsyncSession]":
    # expire_on_commit=False keeps ORM objects usable after an await commit without
    # triggering a lazy reload on attribute access.
    return async_sessionmaker(bind=get_async_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    async with get_async_session_factory()() as session:
        yield session


if TYPE_CHECKING:
    # Declared for static typing; at runtime these resolve lazily through
    # __getattr__, so importing one is what builds the engine, not module load.
    engine: Engine
    async_engine: AsyncEngine
    SessionLocal: sessionmaker[Session]
    AsyncSessionLocal: async_sessionmaker[AsyncSession]


def __getattr__(name: str) -> object:
    """Lazily serve the engines and session factories as module attributes, so
    `from app.db.session import engine / SessionLocal / ...` keeps working while the
    module itself imports without touching the database driver (PEP 562)."""
    if name == "engine":
        return get_engine()
    if name == "async_engine":
        return get_async_engine()
    if name == "SessionLocal":
        return get_session_factory()
    if name == "AsyncSessionLocal":
        return get_async_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
