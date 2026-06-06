from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# --- sync stack (control plane today; migrates onto the async stack slice by slice) ---
engine = create_engine(settings.database_url, echo=False, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- async stack ---------------------------------------------------------------
# Runs alongside the sync stack during the migration. The psycopg3 driver is both
# sync and async, so the same DATABASE_URL (postgresql+psycopg://...) drives the
# async engine with no URL change. expire_on_commit=False keeps ORM objects usable
# after an await commit without triggering a lazy reload on attribute access.
async_engine = create_async_engine(settings.database_url, echo=False)

AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
