"""Canonical usage-event dimension -> column map.

The single source of truth shared by the breakdown metrics endpoint
(``app/api/v1/metrics.py``) and the usage-event list filters
(``app/api/v1/usage_events.py``). Both used to re-declare this mapping
independently and had drifted: ``workflow`` and ``external_user_id`` were being
collapsed onto the ``feature`` and ``user_id`` columns. Keeping one map here means
a public dimension name can never again resolve to the wrong column.

Every public name points at its own first-class column. ``workflow`` and
``feature`` are distinct columns, as are ``external_user_id`` and ``user_id``.
Using a fixed whitelist (not a raw string) also keeps GROUP BY / WHERE columns
injection-safe and the indexes meaningful.
"""

from sqlalchemy.orm import InstrumentedAttribute

from app.models import UsageEvent

DIMENSION_TO_COLUMN: dict[str, InstrumentedAttribute] = {
    "provider": UsageEvent.provider,
    "model": UsageEvent.model,
    "workflow": UsageEvent.workflow,
    "external_user_id": UsageEvent.external_user_id,
    "feature": UsageEvent.feature,
    "customer_id": UsageEvent.customer_id,
    "user_id": UsageEvent.user_id,
    "team": UsageEvent.team,
    "department": UsageEvent.department,
    "environment": UsageEvent.environment,
    "request_type": UsageEvent.request_type,
}
