"""Alert evaluation and delivery.

Turns the stored alert rules into real, deduplicated notifications with a delivery
record behind each one. Two concrete, well-defined behaviours (so "alert_type" is
never a mystery string):

- a rule with ``threshold_usd`` fires when month-to-date project spend reaches it;
- a rule with ``threshold_percent`` fires when any budget owner reaches that
  percent of its cap.

Each crossing fires once per period: a ``dedupe_key`` (rule + period + threshold)
is unique per project, so a re-evaluation finds the prior delivery and skips.
Delivery is best-effort and never raises into the sweep: a send failure is
recorded with status=failed; an unconfigured channel is recorded as skipped.
"""

import smtplib
from datetime import UTC, datetime
from decimal import Decimal
from email.message import EmailMessage

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budgets import evaluate_budgets
from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    DELIVERY_FAILED,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    AlertDelivery,
    AlertRule,
    Project,
    UsageEvent,
)
from app.savings import month_start

logger = get_logger("varsten.alerts")

_ERR_CAP = 500


def _send_email(destination: str, subject: str, body: str) -> tuple[str, str | None]:
    if not settings.smtp_host:
        return DELIVERY_SKIPPED, "smtp not configured"
    try:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from_address
        msg["To"] = destination
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        return DELIVERY_SENT, None
    except Exception as exc:  # delivery must never raise into the sweep
        logger.exception("email alert send failed")
        return DELIVERY_FAILED, str(exc)[:_ERR_CAP]


def _send_slack(destination: str, subject: str, body: str) -> tuple[str, str | None]:
    if not settings.slack_alerts_enabled:
        return DELIVERY_SKIPPED, "slack delivery disabled"
    try:
        resp = httpx.post(destination, json={"text": f"*{subject}*\n{body}"}, timeout=10)
        resp.raise_for_status()
        return DELIVERY_SENT, None
    except Exception as exc:
        logger.exception("slack alert send failed")
        return DELIVERY_FAILED, str(exc)[:_ERR_CAP]


def _deliver(channel: str, destination: str, subject: str, body: str) -> tuple[str, str | None]:
    if channel == "slack":
        return _send_slack(destination, subject, body)
    return _send_email(destination, subject, body)


def _fire_once(
    db: Session,
    project: Project,
    rule: AlertRule,
    dedupe_key: str,
    *,
    alert_type: str,
    subject: str,
    body: str,
    observed_usd: Decimal,
    threshold_usd: Decimal | None = None,
    threshold_percent: Decimal | None = None,
    owner_type: str | None = None,
    owner_key: str | None = None,
) -> AlertDelivery | None:
    """Deliver and record, unless this exact crossing already fired this period."""
    already = db.scalar(
        select(AlertDelivery.id).where(AlertDelivery.project_id == project.id, AlertDelivery.dedupe_key == dedupe_key)
    )
    if already is not None:
        return None
    status, error = _deliver(rule.destination_type, rule.destination, subject, body)
    delivery = AlertDelivery(
        organization_id=project.organization_id,
        project_id=project.id,
        alert_rule_id=rule.id,
        alert_type=alert_type,
        channel=rule.destination_type,
        destination=rule.destination,
        subject=subject,
        body=body,
        observed_usd=observed_usd,
        threshold_usd=threshold_usd,
        threshold_percent=threshold_percent,
        owner_type=owner_type,
        owner_key=owner_key,
        status=status,
        error=error,
        dedupe_key=dedupe_key,
    )
    db.add(delivery)
    db.commit()
    return delivery


def evaluate_and_deliver(db: Session, project: Project, now: datetime | None = None) -> list[AlertDelivery]:
    """Evaluate every enabled alert rule for the project and deliver any that cross."""
    now = now or datetime.now(UTC)
    start = month_start(now)
    period = f"{now:%Y-%m}"
    rules = db.scalars(select(AlertRule).where(AlertRule.project_id == project.id, AlertRule.enabled.is_(True))).all()
    if not rules:
        return []

    spend = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                UsageEvent.project_id == project.id, UsageEvent.received_at >= start
            )
        )
        or 0
    )
    budgets = None
    delivered: list[AlertDelivery] = []

    for rule in rules:
        if rule.threshold_usd is not None:
            if spend >= Decimal(rule.threshold_usd):
                dk = f"{rule.id}:{period}:spend:{rule.threshold_usd}"
                subject = f"Varsten spend alert: ${spend:,.2f} this month"
                body = (
                    f"Month-to-date AI spend for project {project.name} is ${spend:,.2f}, "
                    f"at or above your ${Decimal(rule.threshold_usd):,.2f} alert threshold."
                )
                d = _fire_once(
                    db,
                    project,
                    rule,
                    dk,
                    alert_type="spend",
                    subject=subject,
                    body=body,
                    observed_usd=spend,
                    threshold_usd=Decimal(rule.threshold_usd),
                )
                if d is not None:
                    delivered.append(d)
        elif rule.threshold_percent is not None:
            if budgets is None:
                budgets = evaluate_budgets(db, project, now)
            for b in budgets:
                pct = b.percent_used
                if pct is None or pct < Decimal(rule.threshold_percent):
                    continue
                dk = f"{rule.id}:{period}:budget:{b.owner_type}:{b.owner_key}:{rule.threshold_percent}"
                subject = f"Varsten budget alert: {b.owner_type} '{b.owner_key}' at {pct}%"
                body = (
                    f"Budget owner {b.owner_type} '{b.owner_key}' has used ${b.spend_usd:,.2f} of its "
                    f"${b.budget_usd:,.2f} monthly budget ({pct}%), at or above your "
                    f"{Decimal(rule.threshold_percent)}% alert threshold."
                )
                d = _fire_once(
                    db,
                    project,
                    rule,
                    dk,
                    alert_type="budget",
                    subject=subject,
                    body=body,
                    observed_usd=b.spend_usd,
                    threshold_percent=Decimal(rule.threshold_percent),
                    owner_type=b.owner_type,
                    owner_key=b.owner_key,
                )
                if d is not None:
                    delivered.append(d)

    return delivered


def sweep_all_projects(db: Session, now: datetime | None = None) -> int:
    """Evaluate and deliver alerts across every project. One project's failure never
    stops the sweep. Returns the number of notifications delivered."""
    total = 0
    for project in db.scalars(select(Project)).all():
        try:
            total += len(evaluate_and_deliver(db, project, now))
        except Exception:
            logger.exception("alert sweep failed for project", extra={"project_id": str(project.id)})
            db.rollback()
    return total
