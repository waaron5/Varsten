import uuid

from sqlalchemy import func, select

from app.models import (
    CustomerEconomics,
    LeverConfig,
    Project,
    ProviderConnection,
    Recommendation,
    SavingsAttribution,
    UsageEvent,
)
from app.savings import compute_savings_summary
from scripts.seed_demo import seed


def test_seed_demo_creates_product_story_data_idempotently(db_session):
    first = seed(db_session)
    second = seed(db_session)

    assert first["project_id"] == second["project_id"]
    assert first["api_key"].startswith("vk_")
    assert first["inserted_usage_events"] >= 0
    assert second["inserted_usage_events"] == 0

    project_id = uuid.UUID(first["project_id"])
    events = db_session.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.project_id == project_id))
    levers = db_session.scalar(
        select(func.count()).select_from(LeverConfig).where(LeverConfig.project_id == project_id)
    )
    connections = db_session.scalar(
        select(func.count()).select_from(ProviderConnection).where(ProviderConnection.project_id == project_id)
    )
    customers = db_session.scalar(
        select(func.count()).select_from(CustomerEconomics).where(CustomerEconomics.project_id == project_id)
    )
    proof_rows = db_session.scalar(
        select(func.count()).select_from(SavingsAttribution).where(SavingsAttribution.project_id == project_id)
    )
    gross_savings = db_session.scalar(
        select(func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0)).where(
            SavingsAttribution.project_id == project_id
        )
    )
    recommendation_levers = set(
        db_session.scalars(
            select(Recommendation.lever).where(
                Recommendation.project_id == project_id,
                Recommendation.lever.is_not(None),
            )
        )
    )

    project = db_session.get(Project, project_id)
    summary = compute_savings_summary(db_session, project)

    assert events >= 750
    # Savings are derived from applied recommendations, never seeded constants.
    assert gross_savings > 0
    # Coherent proof on a consistent (run-rated) basis: a cut never saves more
    # than the counterfactual spend, and net is below gross after the fee.
    assert summary["counterfactual_spend_usd"] > summary["actual_spend_usd"]
    assert summary["gross_savings_usd"] < summary["counterfactual_spend_usd"]
    assert summary["net_savings_usd"] < summary["gross_savings_usd"]
    # One LeverConfig per lever in LEVER_DEFAULT_AUTOMATION (now includes
    # prompt_compression).
    assert levers == 6
    assert connections == 3
    assert customers == 3
    assert 1 <= proof_rows <= 3
    assert {
        "smart_routing",
        "semantic_cache",
        "token_trim",
        "model_downshift",
        "batching",
    }.issubset(recommendation_levers)
