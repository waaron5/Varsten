import uuid

from sqlalchemy import func, select

from app.models import (
    CustomerEconomics,
    LeverConfig,
    ProviderConnection,
    Recommendation,
    SavingsAttribution,
    UsageEvent,
)
from scripts.seed_demo import seed


def test_seed_demo_creates_product_story_data_idempotently(db_session):
    first = seed(db_session)
    second = seed(db_session)

    assert first["project_id"] == second["project_id"]
    assert first["api_key"].startswith("vk_")
    assert first["inserted_usage_events"] >= 0
    assert second["inserted_usage_events"] == 0

    project_id = uuid.UUID(first["project_id"])
    events = db_session.scalar(
        select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project_id)
    )
    levers = db_session.scalar(
        select(func.count()).select_from(LeverConfig).where(LeverConfig.project_id == project_id)
    )
    connections = db_session.scalar(
        select(func.count())
        .select_from(ProviderConnection)
        .where(ProviderConnection.project_id == project_id)
    )
    customers = db_session.scalar(
        select(func.count())
        .select_from(CustomerEconomics)
        .where(CustomerEconomics.project_id == project_id)
    )
    proof_rows = db_session.scalar(
        select(func.count())
        .select_from(SavingsAttribution)
        .where(SavingsAttribution.project_id == project_id)
    )
    recommendation_levers = set(
        db_session.scalars(
            select(Recommendation.lever).where(
                Recommendation.project_id == project_id,
                Recommendation.lever.is_not(None),
            )
        )
    )

    assert events == 11
    assert levers == 5
    assert connections == 3
    assert customers == 3
    assert proof_rows == 3
    assert {
        "smart_routing",
        "semantic_cache",
        "token_trim",
        "cheaper_model",
        "batching",
    }.issubset(recommendation_levers)
