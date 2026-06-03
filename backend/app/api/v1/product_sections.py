import uuid
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user, resolve_project
from app.db.session import get_db
from app.models import (
    AlertRule,
    ApiKey,
    BudgetRule,
    CustomerEconomics,
    LeverConfig,
    MonthlyReport,
    OrgMembership,
    Project,
    ProviderConnection,
    QualityGuardrail,
    Recommendation,
    RecommendationAction,
    SavingsAttribution,
    UsageEvent,
    User,
)
from app.recommendations import ensure_recommendations_fresh
from app.savings import compute_savings_summary, record_applied_savings
from app.schemas.recommendation import RecommendationOut, RecommendationUpdate

router = APIRouter(tags=["product-sections"])

LEVERS = (
    ("smart_routing", "approve"),
    ("semantic_cache", "auto"),
    ("token_trim", "auto"),
    ("cheaper_model", "approve"),
    ("batching", "auto"),
)
VALID_LEVERS = {lever for lever, _ in LEVERS}


class LeverConfigUpdate(BaseModel):
    enabled: bool | None = None
    automation_mode: Literal["auto", "approve"] | None = None


class MonthlyReportUpdate(BaseModel):
    status: Literal["draft", "published"]


class QualityGuardrailCreate(BaseModel):
    route: str = Field(min_length=1, max_length=255)
    min_model_tier: str | None = None
    eval_gate: str | None = None
    min_eval_score: Decimal | None = None
    max_latency_ms: int | None = Field(default=None, ge=0)
    auto_rollback_enabled: bool = True
    enabled: bool = True


class BudgetRuleCreate(BaseModel):
    owner_type: Literal["team", "feature", "customer"]
    owner_key: str = Field(min_length=1, max_length=255)
    monthly_budget_usd: Decimal = Field(ge=0)
    hard_cap_enabled: bool = False
    enabled: bool = True


class AlertRuleCreate(BaseModel):
    alert_type: str = Field(min_length=1, max_length=64)
    threshold_usd: Decimal | None = Field(default=None, ge=0)
    threshold_percent: Decimal | None = Field(default=None, ge=0)
    destination_type: Literal["email", "slack"]
    destination: str = Field(min_length=1, max_length=255)
    enabled: bool = True


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(start: datetime) -> datetime:
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def _money(value: Decimal | None) -> Decimal:
    return value or Decimal("0")


def _json_money(value: Decimal | None) -> str:
    return str(_money(value))


def _json_decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _ensure_lever_configs(db: Session, project: Project) -> list[LeverConfig]:
    existing = {
        config.lever: config
        for config in db.scalars(
            select(LeverConfig).where(LeverConfig.project_id == project.id)
        )
    }
    changed = False
    for lever, default_mode in LEVERS:
        if lever not in existing:
            config = LeverConfig(
                organization_id=project.organization_id,
                project_id=project.id,
                lever=lever,
                automation_mode=default_mode,
            )
            db.add(config)
            existing[lever] = config
            changed = True
    if changed:
        db.commit()
    return list(
        db.scalars(
            select(LeverConfig)
            .where(LeverConfig.project_id == project.id)
            .order_by(LeverConfig.lever.asc())
        )
    )


def _refresh_open_recommendations(db: Session, project: Project) -> list[Recommendation]:
    ensure_recommendations_fresh(db, project)
    return list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.project_id == project.id, Recommendation.status == "open")
            .order_by(
                Recommendation.estimated_monthly_savings_usd.desc().nulls_last(),
                Recommendation.created_at.desc(),
            )
        )
    )


def _data_quality(db: Session, project: Project) -> dict:
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    row = db.execute(
        select(
            func.count().label("requests"),
            func.count().filter(UsageEvent.pricing_status == "priced").label("priced"),
            func.count().filter(UsageEvent.pricing_status != "priced").label("unpriced"),
            func.count().filter(UsageEvent.feature.is_not(None)).label("feature_tagged"),
            func.count().filter(UsageEvent.customer_id.is_not(None)).label("customer_tagged"),
            func.count().filter(UsageEvent.team.is_not(None)).label("team_tagged"),
            func.count()
            .filter((UsageEvent.environment.is_not(None)) & (UsageEvent.environment != "unknown"))
            .label("environment_tagged"),
        ).where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
    ).one()

    def share(count: int) -> Decimal | None:
        return Decimal(count) / Decimal(row.requests) if row.requests else None

    trust_score = share(row.priced)
    return {
        "requests_month": row.requests,
        "trust_score": trust_score,
        "priced_event_count": row.priced,
        "unpriced_event_count": row.unpriced,
        "metadata_quality": {
            "feature": share(row.feature_tagged),
            "customer_id": share(row.customer_tagged),
            "team": share(row.team_tagged),
            "environment": share(row.environment_tagged),
        },
    }


def _assert_member(user: User, project: Project, db: Session) -> None:
    membership = db.scalar(
        select(OrgMembership.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.organization_id == project.organization_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a member")


def _recommendation_payload(rec: Recommendation) -> dict:
    return RecommendationOut.model_validate(rec).model_dump()


def _action_payload(action: RecommendationAction) -> dict:
    return {
        "id": action.id,
        "recommendation_id": action.recommendation_id,
        "lever": action.lever,
        "action_type": action.action_type,
        "status": action.status,
        "source": action.source,
        "title": action.title,
        "detail": action.detail,
        "estimated_savings_usd": action.estimated_savings_usd,
        "realized_savings_usd": action.realized_savings_usd,
        "occurred_at": action.occurred_at,
    }


def _lever_payload(config: LeverConfig) -> dict:
    return {
        "id": config.id,
        "organization_id": config.organization_id,
        "project_id": config.project_id,
        "lever": config.lever,
        "enabled": config.enabled,
        "automation_mode": config.automation_mode,
        "savings_to_date_usd": config.savings_to_date_usd,
        "quality_delta_percent": config.quality_delta_percent,
        "paused_at": config.paused_at,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


def _quality_guardrail_payload(rule: QualityGuardrail) -> dict:
    return {
        "id": rule.id,
        "route": rule.route,
        "min_model_tier": rule.min_model_tier,
        "eval_gate": rule.eval_gate,
        "min_eval_score": rule.min_eval_score,
        "max_latency_ms": rule.max_latency_ms,
        "auto_rollback_enabled": rule.auto_rollback_enabled,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _budget_rule_payload(rule: BudgetRule) -> dict:
    return {
        "id": rule.id,
        "owner_type": rule.owner_type,
        "owner_key": rule.owner_key,
        "monthly_budget_usd": rule.monthly_budget_usd,
        "hard_cap_enabled": rule.hard_cap_enabled,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _alert_rule_payload(rule: AlertRule) -> dict:
    return {
        "id": rule.id,
        "alert_type": rule.alert_type,
        "threshold_usd": rule.threshold_usd,
        "threshold_percent": rule.threshold_percent,
        "destination_type": rule.destination_type,
        "destination": rule.destination,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _provider_connection_payload(connection: ProviderConnection) -> dict:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "connection_method": connection.connection_method,
        "status": connection.status,
        "last_sync_at": connection.last_sync_at,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


def _monthly_report_payload(report: MonthlyReport) -> dict:
    return {
        "id": report.id,
        "organization_id": report.organization_id,
        "project_id": report.project_id,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "title": report.title,
        "executive_summary": report.executive_summary,
        "status": report.status,
        "share_token": report.share_token,
        "published_at": report.published_at,
        "counterfactual_spend_usd": report.counterfactual_spend_usd,
        "actual_spend_usd": report.actual_spend_usd,
        "gross_savings_usd": report.gross_savings_usd,
        "varsten_fee_usd": report.varsten_fee_usd,
        "net_savings_usd": report.net_savings_usd,
        "trust_score": report.trust_score,
        "priced_event_count": report.priced_event_count,
        "unpriced_event_count": report.unpriced_event_count,
        "requests_month": report.requests_month,
        "metadata_quality": report.metadata_quality,
        "attribution_rows": report.attribution_rows,
        "top_recommendations": report.top_recommendations,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def _report_snapshot(db: Session, project: Project) -> dict:
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    end = _next_month_start(start)
    quality = _data_quality(db, project)
    savings = compute_savings_summary(db, project, now)
    attribution_rows = [
        {
            "lever": row.lever,
            "measurement_method": row.measurement_method,
            "gross_savings_usd": _json_money(row.gross),
            "net_savings_usd": _json_money(row.net),
            "actions": row.actions,
        }
        for row in db.execute(
            select(
                SavingsAttribution.lever,
                SavingsAttribution.measurement_method,
                func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).label("gross"),
                func.coalesce(func.sum(SavingsAttribution.net_savings_usd), 0).label("net"),
                func.count().label("actions"),
            )
            .where(
                SavingsAttribution.project_id == project.id,
                SavingsAttribution.period_start >= start,
                SavingsAttribution.period_start < end,
            )
            .group_by(SavingsAttribution.lever, SavingsAttribution.measurement_method)
            .order_by(func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).desc())
        )
    ]
    top_recommendations = [
        {
            "id": str(rec.id),
            "lever": rec.lever,
            "title": rec.title,
            "risk_level": rec.risk_level,
            "confidence": rec.confidence,
            "estimated_monthly_savings_usd": _json_decimal(rec.estimated_monthly_savings_usd),
        }
        for rec in db.scalars(
            select(Recommendation)
            .where(Recommendation.project_id == project.id, Recommendation.status == "open")
            .order_by(
                Recommendation.estimated_monthly_savings_usd.desc().nulls_last(),
                Recommendation.created_at.desc(),
            )
            .limit(5)
        )
    ]
    summary = (
        f"Varsten saved {_money(savings['gross_savings_usd']):,.2f} gross this month, "
        f"{_money(savings['net_savings_usd']):,.2f} net after fee, across "
        f"{quality['requests_month']} measured requests."
    )
    return {
        "period_start": start,
        "period_end": end,
        "title": f"Varsten Executive Report - {start:%B %Y}",
        "executive_summary": summary,
        "counterfactual_spend_usd": _money(savings["counterfactual_spend_usd"]),
        "actual_spend_usd": _money(savings["actual_spend_usd"]),
        "gross_savings_usd": _money(savings["gross_savings_usd"]),
        "varsten_fee_usd": _money(savings["varsten_fee_usd"]),
        "net_savings_usd": _money(savings["net_savings_usd"]),
        "trust_score": quality["trust_score"],
        "priced_event_count": quality["priced_event_count"],
        "unpriced_event_count": quality["unpriced_event_count"],
        "requests_month": quality["requests_month"],
        "metadata_quality": {
            key: _json_decimal(value)
            for key, value in quality["metadata_quality"].items()
        },
        "attribution_rows": attribution_rows,
        "top_recommendations": top_recommendations,
    }


def _api_key_payload(api_key: ApiKey) -> dict:
    return {
        "id": api_key.id,
        "project_id": api_key.project_id,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "last_used_at": api_key.last_used_at,
        "revoked_at": api_key.revoked_at,
        "created_at": api_key.created_at,
    }


@router.get("/command-center")
def command_center(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    recommendations = _refresh_open_recommendations(db, project)
    quality = _data_quality(db, project)
    spend_row = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend_month"),
            func.count().label("requests_month"),
        ).where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
    ).one()
    summary = compute_savings_summary(db, project, now)
    actions = list(
        db.scalars(
            select(RecommendationAction)
            .where(RecommendationAction.project_id == project.id)
            .order_by(RecommendationAction.occurred_at.desc())
            .limit(10)
        )
    )
    top_waste = recommendations[0] if recommendations else None
    return {
        "live_savings": {
            "spend_month": spend_row.spend_month,
            "saved_month": summary["gross_savings_usd"],
            "net_saved_month": summary["net_savings_usd"],
            "annual_run_rate": _money(summary["gross_savings_usd"]) * Decimal("12"),
            "trust_score": quality["trust_score"],
        },
        "decision_queue": [_recommendation_payload(rec) for rec in recommendations[:5]],
        "recent_actions": [_action_payload(action) for action in actions],
        "top_waste_now": _recommendation_payload(top_waste) if top_waste else None,
        "requests_month": spend_row.requests_month,
    }


@router.get("/engine/recommendations", response_model=list[RecommendationOut])
def engine_recommendations(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[Recommendation]:
    return _refresh_open_recommendations(db, project)


@router.patch("/engine/recommendations/{recommendation_id}", response_model=RecommendationOut)
def engine_update_recommendation(
    recommendation_id: uuid.UUID,
    payload: RecommendationUpdate,
    project: Project = Depends(resolve_project),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Recommendation:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None or recommendation.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recommendation not found")
    _assert_member(user, project, db)
    now = datetime.now(timezone.utc)
    recommendation.status = payload.status
    recommendation.updated_at = now
    recommendation.resolved_at = now if payload.status != "open" else None
    if payload.status == "applied":
        # Applying writes the action, the derived savings attribution, and the
        # refreshed lever total in one place, so Proof reflects real applied cuts.
        record_applied_savings(
            db, project, recommendation, actor_user_id=user.id, source="user", now=now
        )
    elif payload.status != "open":
        db.add(
            RecommendationAction(
                organization_id=project.organization_id,
                project_id=project.id,
                recommendation_id=recommendation.id,
                actor_user_id=user.id,
                lever=recommendation.lever,
                action_type=payload.status,
                status="completed",
                source="user",
                title=recommendation.title,
                estimated_savings_usd=recommendation.estimated_monthly_savings_usd,
                occurred_at=now,
            )
        )
    db.commit()
    db.refresh(recommendation)
    return recommendation


@router.get("/engine/levers", response_model=None)
def engine_levers(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [_lever_payload(config) for config in _ensure_lever_configs(db, project)]


@router.patch("/engine/levers/{lever}", response_model=None)
def engine_update_lever(
    lever: str,
    payload: LeverConfigUpdate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    if lever not in VALID_LEVERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown lever")
    _ensure_lever_configs(db, project)
    config = db.scalar(
        select(LeverConfig).where(
            LeverConfig.project_id == project.id, LeverConfig.lever == lever
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lever not found")
    if payload.enabled is not None:
        config.enabled = payload.enabled
        config.paused_at = None if payload.enabled else datetime.now(timezone.utc)
    if payload.automation_mode is not None:
        config.automation_mode = payload.automation_mode
    db.commit()
    db.refresh(config)
    return _lever_payload(config)


@router.get("/engine/automation")
def engine_automation(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "lever": config.lever,
            "enabled": config.enabled,
            "automation_mode": config.automation_mode,
            "risk_profile": "low" if config.lever in {"semantic_cache", "token_trim", "batching"} else "medium",
        }
        for config in _ensure_lever_configs(db, project)
    ]


@router.get("/reports", response_model=None)
def reports(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        _monthly_report_payload(report)
        for report in db.scalars(
            select(MonthlyReport)
            .where(MonthlyReport.project_id == project.id)
            .order_by(MonthlyReport.period_start.desc(), MonthlyReport.created_at.desc())
        )
    ]


@router.post("/reports", status_code=status.HTTP_201_CREATED, response_model=None)
def create_report(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    snapshot = _report_snapshot(db, project)
    report = db.scalar(
        select(MonthlyReport).where(
            MonthlyReport.project_id == project.id,
            MonthlyReport.period_start == snapshot["period_start"],
            MonthlyReport.period_end == snapshot["period_end"],
        )
    )
    now = datetime.now(timezone.utc)
    if report is None:
        report = MonthlyReport(
            organization_id=project.organization_id,
            project_id=project.id,
            share_token=secrets.token_urlsafe(32),
            status="published",
            published_at=now,
            **snapshot,
        )
        db.add(report)
    else:
        for key, value in snapshot.items():
            setattr(report, key, value)
        report.status = "published"
        report.published_at = report.published_at or now
    db.commit()
    db.refresh(report)
    return _monthly_report_payload(report)


@router.get("/reports/{report_id}", response_model=None)
def report_detail(
    report_id: uuid.UUID,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    report = db.get(MonthlyReport, report_id)
    if report is None or report.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return _monthly_report_payload(report)


@router.patch("/reports/{report_id}", response_model=None)
def update_report(
    report_id: uuid.UUID,
    payload: MonthlyReportUpdate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    report = db.get(MonthlyReport, report_id)
    if report is None or report.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    report.status = payload.status
    report.published_at = datetime.now(timezone.utc) if payload.status == "published" else None
    db.commit()
    db.refresh(report)
    return _monthly_report_payload(report)


@router.get("/public/reports/{share_token}", response_model=None)
def public_report(
    share_token: str,
    db: Session = Depends(get_db),
) -> dict:
    report = db.scalar(select(MonthlyReport).where(MonthlyReport.share_token == share_token))
    if report is None or report.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return _monthly_report_payload(report)


@router.get("/proof/savings")
def proof_savings(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    # actual = real month-to-date spend run-rated; counterfactual = actual plus the
    # savings attributed to applied recommendations. Every number is derived.
    summary = compute_savings_summary(db, project)
    return {
        **summary,
        "measurement_note": "v1 savings are the applied recommendations' run-rate estimates, labelled by measurement method. Randomized-holdback measurement is the production upgrade.",
    }


@router.get("/proof/attribution")
def proof_attribution(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.execute(
            select(
                SavingsAttribution.lever,
                SavingsAttribution.measurement_method,
                func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).label("gross"),
                func.coalesce(func.sum(SavingsAttribution.net_savings_usd), 0).label("net"),
                func.count().label("actions"),
            )
            .where(SavingsAttribution.project_id == project.id)
            .group_by(SavingsAttribution.lever, SavingsAttribution.measurement_method)
            .order_by(func.coalesce(func.sum(SavingsAttribution.gross_savings_usd), 0).desc())
        )
    )
    return {
        "rows": [
            {
                "lever": row.lever,
                "measurement_method": row.measurement_method,
                "gross_savings_usd": row.gross,
                "net_savings_usd": row.net,
                "actions": row.actions,
            }
            for row in rows
        ],
        "methodology": "V1 exposes estimated or backtested attribution. Production proof later uses live holdback or direct measured avoidance.",
    }


@router.get("/proof/data-quality")
def proof_data_quality(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    return _data_quality(db, project)


@router.get("/guardrails/quality", response_model=None)
def guardrails_quality(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        _quality_guardrail_payload(rule)
        for rule in db.scalars(
            select(QualityGuardrail)
            .where(QualityGuardrail.project_id == project.id)
            .order_by(QualityGuardrail.route.asc())
        )
    ]


@router.post("/guardrails/quality", status_code=status.HTTP_201_CREATED, response_model=None)
def create_quality_guardrail(
    payload: QualityGuardrailCreate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rule = QualityGuardrail(
        organization_id=project.organization_id,
        project_id=project.id,
        **payload.model_dump(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _quality_guardrail_payload(rule)


@router.get("/guardrails/budgets", response_model=None)
def guardrails_budgets(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        _budget_rule_payload(rule)
        for rule in db.scalars(
            select(BudgetRule)
            .where(BudgetRule.project_id == project.id)
            .order_by(BudgetRule.owner_type.asc(), BudgetRule.owner_key.asc())
        )
    ]


@router.post("/guardrails/budgets", status_code=status.HTTP_201_CREATED, response_model=None)
def create_budget_rule(
    payload: BudgetRuleCreate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rule = BudgetRule(
        organization_id=project.organization_id,
        project_id=project.id,
        **payload.model_dump(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _budget_rule_payload(rule)


@router.get("/guardrails/alerts", response_model=None)
def guardrails_alerts(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        _alert_rule_payload(rule)
        for rule in db.scalars(
            select(AlertRule)
            .where(AlertRule.project_id == project.id)
            .order_by(AlertRule.created_at.desc())
        )
    ]


@router.post("/guardrails/alerts", status_code=status.HTTP_201_CREATED, response_model=None)
def create_alert_rule(
    payload: AlertRuleCreate,
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rule = AlertRule(
        organization_id=project.organization_id,
        project_id=project.id,
        **payload.model_dump(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _alert_rule_payload(rule)


@router.get("/analysis/spend")
def analysis_spend(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.execute(
            select(
                UsageEvent.team,
                UsageEvent.feature,
                UsageEvent.provider,
                func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
                func.count().label("requests"),
            )
            .where(UsageEvent.project_id == project.id)
            .group_by(UsageEvent.team, UsageEvent.feature, UsageEvent.provider)
            .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0).desc())
            .limit(50)
        )
    )
    return {
        "rows": [
            {
                "team": row.team,
                "feature": row.feature,
                "provider": row.provider,
                "spend_usd": row.spend,
                "requests": row.requests,
            }
            for row in rows
        ]
    }


@router.get("/analysis/customers")
def analysis_customers(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    spend_rows = {
        row.customer_id: row
        for row in db.execute(
            select(
                UsageEvent.customer_id,
                func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("ai_cost_usd"),
                func.count().label("requests"),
            )
            .where(UsageEvent.project_id == project.id, UsageEvent.customer_id.is_not(None))
            .group_by(UsageEvent.customer_id)
        )
    }
    economics = list(
        db.scalars(
            select(CustomerEconomics)
            .where(CustomerEconomics.project_id == project.id)
            .order_by(CustomerEconomics.period_end.desc())
        )
    )
    rows = []
    seen = set()
    for econ in economics:
        spend = spend_rows.get(econ.customer_id)
        ai_cost = _money(spend.ai_cost_usd if spend else None)
        margin = econ.revenue_usd - ai_cost
        seen.add(econ.customer_id)
        rows.append(
            {
                "customer_id": econ.customer_id,
                "customer_name": econ.customer_name,
                "revenue_usd": econ.revenue_usd,
                "ai_cost_usd": ai_cost,
                "gross_margin_usd": margin,
                "status": "negative_margin" if margin < 0 else "healthy",
                "requests": spend.requests if spend else 0,
            }
        )
    for customer_id, spend in spend_rows.items():
        if customer_id in seen:
            continue
        rows.append(
            {
                "customer_id": customer_id,
                "customer_name": None,
                "revenue_usd": None,
                "ai_cost_usd": spend.ai_cost_usd,
                "gross_margin_usd": None,
                "status": "missing_revenue",
                "requests": spend.requests,
            }
        )
    return {"rows": rows}


@router.get("/analysis/models")
def analysis_models(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.execute(
            select(
                UsageEvent.provider,
                UsageEvent.model,
                func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
                func.count().label("requests"),
            )
            .where(UsageEvent.project_id == project.id)
            .group_by(UsageEvent.provider, UsageEvent.model)
            .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0).desc())
        )
    )
    return {
        "rows": [
            {
                "provider": row.provider,
                "model": row.model,
                "spend_usd": row.spend,
                "requests": row.requests,
                "avg_cost_per_request_usd": row.spend / row.requests if row.requests else None,
            }
            for row in rows
        ]
    }


@router.get("/admin/connections")
def admin_connections(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    connections = list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.project_id == project.id)
            .order_by(ProviderConnection.provider.asc())
        )
    )
    keys = list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.project_id == project.id)
            .order_by(ApiKey.created_at.desc())
        )
    )
    return {
        "provider_connections": [
            _provider_connection_payload(connection) for connection in connections
        ],
        "api_keys": [_api_key_payload(api_key) for api_key in keys],
    }


@router.get("/admin/team")
def admin_team(
    project: Project = Depends(resolve_project),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.execute(
            select(OrgMembership, User)
            .join(User, User.id == OrgMembership.user_id)
            .where(OrgMembership.organization_id == project.organization_id)
            .order_by(User.email.asc())
        )
    )
    return {
        "members": [
            {
                "id": membership.id,
                "user_id": user.id,
                "email": user.email,
                "name": user.name,
                "role": membership.role,
            }
            for membership, user in rows
        ],
        "roles": ["owner", "admin", "member", "proof_viewer"],
    }


@router.get("/admin/billing-security")
def admin_billing_security(project: Project = Depends(resolve_project)) -> dict:
    return {
        "plan": "verified_savings_v1",
        "pricing_model": "percentage_of_verified_savings_with_floor",
        "verified_savings_fee_percent": None,
        "security_posture": {
            "deployment_mode": "metadata_mode",
            "content_storage": "not_collected_in_metadata_mode",
            "soc2_status": "not_started",
            "data_controls": ["api_key_auth", "tenant_scoped_projects", "pricing_audit_trail"],
        },
    }
