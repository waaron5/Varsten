import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.agent_loops import detect_agent_loops
from app.engine.prefix_analysis import propose_prefix_restructure
from app.engine.route_identity import canonical_route_key
from app.levers import LEVER_MODEL_DOWNSHIFT
from app.models import ModelCatalog, ModelPrice, Project, Recommendation, RequestDecisionEvent, UsageEvent

OPEN = "open"

# Not all of a route's traffic clears a lower-cost model's quality gate, so model
# swaps and routing only claim savings on an eligible share of traffic. A
# documented assumption, refined per route by the eval harness later.
ELIGIBLE_SHARE = Decimal("0.70")

# Prefix-stability analysis (prompt-cache orchestration). Below MIN samples the
# measured share is ignored and the conservative default applies; a dominant-hash
# share at or above STABLE means "enable caching, the prefix already repeats";
# at or below UNSTABLE (with big prompts) means "restructure the prompt so its
# prefix stops churning".
PREFIX_STABILITY_MIN_SAMPLES = 20
PREFIX_STABLE_SHARE = 0.7
PREFIX_UNSTABLE_SHARE = 0.4
# The conservative fallback when no fingerprint evidence exists (metadata-mode
# customers, pre-instrumentation traffic): assume half the uncached input is a
# stable, cacheable prefix.
PREFIX_DEFAULT_CACHEABLE_SHARE = Decimal("0.5")


@dataclass(frozen=True)
class RecommendationSeed:
    dedupe_key: str
    type: str
    title: str
    description: str
    estimated_monthly_savings_usd: Decimal | None
    risk_level: str
    confidence: str
    lever: str | None = None
    target_type: str | None = None
    target_key: str | None = None
    rationale: str | None = None
    monthly_request_volume: int | None = None
    quality_delta_percent: Decimal | None = None
    measurement_method: str = "estimated"
    related_provider: str | None = None
    related_model: str | None = None
    related_feature: str | None = None
    related_customer_id: str | None = None
    related_environment: str | None = None
    details: dict | None = None


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _upsert(db: Session, project: Project, seed: RecommendationSeed) -> None:
    existing = db.scalar(
        select(Recommendation).where(
            Recommendation.project_id == project.id,
            Recommendation.dedupe_key == seed.dedupe_key,
        )
    )
    if existing is not None:
        if existing.status != OPEN:
            return
        existing.title = seed.title
        existing.description = seed.description
        existing.lever = seed.lever
        existing.target_type = seed.target_type
        existing.target_key = seed.target_key
        existing.rationale = seed.rationale
        existing.estimated_monthly_savings_usd = seed.estimated_monthly_savings_usd
        existing.monthly_request_volume = seed.monthly_request_volume
        existing.quality_delta_percent = seed.quality_delta_percent
        existing.measurement_method = seed.measurement_method
        existing.risk_level = seed.risk_level
        existing.confidence = seed.confidence
        existing.related_provider = seed.related_provider
        existing.related_model = seed.related_model
        existing.related_feature = seed.related_feature
        existing.related_customer_id = seed.related_customer_id
        existing.related_environment = seed.related_environment
        existing.details = seed.details
        existing.updated_at = datetime.now(UTC)
        return

    db.add(
        Recommendation(
            organization_id=project.organization_id,
            project_id=project.id,
            dedupe_key=seed.dedupe_key,
            type=seed.type,
            lever=seed.lever,
            target_type=seed.target_type,
            target_key=seed.target_key,
            title=seed.title,
            description=seed.description,
            rationale=seed.rationale,
            estimated_monthly_savings_usd=seed.estimated_monthly_savings_usd,
            monthly_request_volume=seed.monthly_request_volume,
            quality_delta_percent=seed.quality_delta_percent,
            measurement_method=seed.measurement_method,
            risk_level=seed.risk_level,
            confidence=seed.confidence,
            related_provider=seed.related_provider,
            related_model=seed.related_model,
            related_feature=seed.related_feature,
            related_customer_id=seed.related_customer_id,
            related_environment=seed.related_environment,
            details=seed.details,
        )
    )


def _money(value: Decimal | None) -> Decimal:
    return value or Decimal("0")


def _run_rate(value: Decimal, now: datetime) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return value / Decimal(now.day) * Decimal(calendar.monthrange(now.year, now.month)[1])


def _target_name(request_type: str | None, feature: str | None) -> str:
    if request_type and feature:
        return f"{feature} / {request_type}"
    return feature or request_type or "unknown workload"


def _latest_price(db: Session, model_key: str, provider: str) -> ModelPrice | None:
    base = select(ModelPrice).where(ModelPrice.model_key == model_key)
    for stmt in (base.where(ModelPrice.provider == provider), base):
        row = db.scalars(stmt.order_by(ModelPrice.effective_at.desc()).limit(1)).first()
        if row is not None:
            return row
    return None


def _model_catalog(db: Session, model_key: str, provider: str) -> ModelCatalog | None:
    base = select(ModelCatalog).where(ModelCatalog.model_key == model_key)
    for stmt in (base.where(ModelCatalog.provider == provider), base):
        row = db.scalars(stmt.limit(1)).first()
        if row is not None:
            return row
    return None


def _priced_cost(
    price: ModelPrice,
    input_tokens: int,
    output_tokens: int,
    *,
    use_batch: bool = False,
) -> Decimal:
    input_rate = (
        price.input_cost_per_token_batch
        if use_batch and price.input_cost_per_token_batch is not None
        else price.input_cost_per_token
    )
    output_rate = (
        price.output_cost_per_token_batch
        if use_batch and price.output_cost_per_token_batch is not None
        else price.output_cost_per_token
    )
    return input_tokens * input_rate + output_tokens * output_rate


def _route_key(request_type: str | None, feature: str | None) -> str:
    return f"{feature or 'unknown'}:{request_type or 'unknown'}"


def _add_token_trim_recommendation(
    db: Session, project: Project, start: datetime, now: datetime, total_spend: Decimal
) -> None:
    if total_spend <= 0:
        return
    rows = db.execute(
        select(
            UsageEvent.request_type,
            UsageEvent.feature,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(UsageEvent.request_type, UsageEvent.feature)
        .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0).desc())
        .limit(5)
    )
    for row in rows:
        output_tokens = int(row.output_tokens or 0)
        input_tokens = int(row.input_tokens or 0)
        spend = _money(row.spend)
        if output_tokens <= 0 or input_tokens / output_tokens < 8 or spend <= 0:
            continue
        target = _target_name(row.request_type, row.feature)
        savings = _run_rate(spend * Decimal("0.15"), now)
        # The proxy resolves the trim transform by model, so carry the route's
        # dominant model (most input tokens) as the execution target.
        top = db.execute(
            select(
                UsageEvent.provider,
                UsageEvent.model,
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            )
            .where(
                UsageEvent.project_id == project.id,
                UsageEvent.received_at >= start,
                UsageEvent.request_type.is_not_distinct_from(row.request_type),
                UsageEvent.feature.is_not_distinct_from(row.feature),
            )
            .group_by(UsageEvent.provider, UsageEvent.model)
            .order_by(func.coalesce(func.sum(UsageEvent.input_tokens), 0).desc())
            .limit(1)
        ).first()
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"token_trim:{_route_key(row.request_type, row.feature)}:{now:%Y-%m}",
                type="token_trim",
                lever="token_trim",
                title=f"Trim context for {target}",
                description=f"{target} sends {input_tokens / max(output_tokens, 1):.1f}x as many input tokens as output tokens. Trim retrieval/context before the model call.",
                rationale="High input-to-output ratio is the strongest metadata-only signal for token trimming.",
                estimated_monthly_savings_usd=savings,
                monthly_request_volume=int(row.requests or 0),
                risk_level="medium",
                confidence="medium",
                target_type="route",
                target_key=_route_key(row.request_type, row.feature),
                related_provider=top.provider if top else None,
                related_model=top.model if top else None,
                related_feature=row.feature,
            ),
        )
        return


def _prefix_stability(db: Session, project: Project, start: datetime) -> dict[str, tuple[int, float]]:
    """Measured prefix stability per route: route_key -> (samples, dominant share).

    The dominant share is the fraction of the route's fingerprinted requests that
    repeat its single most common cacheable-prefix hash — the share a provider
    prompt cache could actually serve at the cache-read rate. Fail-open: any
    error returns an empty map and the caller falls back to its default."""
    try:
        rows = db.execute(
            select(
                RequestDecisionEvent.route_key,
                RequestDecisionEvent.prefix_hash,
                func.count().label("n"),
            )
            .where(
                RequestDecisionEvent.project_id == project.id,
                RequestDecisionEvent.created_at >= start,
                RequestDecisionEvent.prefix_hash.isnot(None),
                RequestDecisionEvent.route_key.isnot(None),
            )
            .group_by(RequestDecisionEvent.route_key, RequestDecisionEvent.prefix_hash)
        ).all()
    except Exception:
        return {}
    totals: dict[str, int] = {}
    dominant: dict[str, int] = {}
    for row in rows:
        key = str(row.route_key)
        totals[key] = totals.get(key, 0) + int(row.n)
        dominant[key] = max(dominant.get(key, 0), int(row.n))
    return {key: (total, dominant[key] / total) for key, total in totals.items() if total > 0}


def _add_agent_loop_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    """Redundant LLM calls inside client traces (agent loops), from measured
    decision-ledger evidence. The fix lives in the customer's workflow, so this is
    always a recommendation, never something the engine executes."""
    findings = detect_agent_loops(db, project, start)
    if not findings:
        return
    top = findings[0]
    monthly_waste = _run_rate(top.wasted_cost_usd, now)
    if monthly_waste <= 0:
        return
    _upsert(
        db,
        project,
        RecommendationSeed(
            dedupe_key=f"agent_loop:{top.route_key}:{now:%Y-%m}",
            type="agent_loop",
            lever=None,
            title=f"Remove redundant LLM calls in {top.route_key}",
            description=(
                f"{top.affected_traces} traces on {top.route_key} repeated an identical request "
                f"{top.redundant_calls} times this month ({top.total_calls_in_loops} calls where "
                f"{top.total_calls_in_loops - top.redundant_calls} would do). Each repeat re-asks the model "
                f"something the workflow already asked in the same run; memoize the first answer or drop the "
                f"duplicate step."
            ),
            rationale=(
                "Requests sharing a trace id and an identical request fingerprint are the same question asked "
                "twice in one workflow run; the repeats' cost is measured from the ledger, not modeled."
            ),
            estimated_monthly_savings_usd=monthly_waste,
            monthly_request_volume=top.total_calls_in_loops,
            risk_level="low",
            confidence="high",
            target_type="route",
            target_key=top.route_key,
            related_model=top.model or None,
        ),
    )


def _add_prompt_cache_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    """Prompt caching from real token data. A route that repeatedly sends a large
    input prompt at a low cache hit rate is paying full input price for tokens a
    provider prompt cache would bill at the cheaper cache-read rate. Savings use
    the catalog's real cache-read rate delta, not a flat percentage.

    Where the proxy has fingerprinted the route's cacheable prefix, the measured
    dominant-hash share replaces the flat cacheable-share assumption: a stable
    prefix strengthens the enable-caching recommendation with measured evidence,
    and an unstable one flips it to a restructure recommendation (the cache
    cannot help until the prefix stops churning)."""
    stability = _prefix_stability(db, project, start)
    rows = db.execute(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.request_type,
            UsageEvent.feature,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.cached_input_tokens), 0).label("cached_input_tokens"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.request_type,
            UsageEvent.feature,
        )
        .order_by(func.coalesce(func.sum(UsageEvent.input_tokens), 0).desc())
        .limit(20)
    )
    for row in rows:
        requests = int(row.requests or 0)
        input_tokens = int(row.input_tokens or 0)
        cached = int(row.cached_input_tokens or 0)
        # Caching only pays off on repeated, large-prompt routes that are not
        # already mostly cached.
        if requests < 20 or input_tokens <= 0:
            continue
        avg_input = input_tokens / requests
        hit_rate = cached / input_tokens if input_tokens else 0.0
        if avg_input < 1500 or hit_rate >= 0.5:
            continue
        price = _latest_price(db, row.model, row.provider)
        if price is None or price.cache_read_input_token_cost is None:
            continue
        rate_delta = price.input_cost_per_token - price.cache_read_input_token_cost
        if rate_delta <= 0:
            continue

        # Measured prefix stability for this route, when the proxy fingerprinted
        # enough of its traffic; otherwise the conservative default share.
        canonical = canonical_route_key(feature=row.feature, request_type=row.request_type)
        samples, dominant_share = stability.get(canonical, (0, 0.0))
        measured = samples >= PREFIX_STABILITY_MIN_SAMPLES
        target = _target_name(row.request_type, row.feature)

        if measured and dominant_share <= PREFIX_UNSTABLE_SHARE:
            # The prefix churns: a provider cache cannot help until the prompt is
            # restructured (volatile content out of the leading system/tools block).
            # Savings are what a stabilized prefix would earn, so they stay a
            # conservative estimate rather than a measured claim.
            cacheable_tokens = Decimal(input_tokens - cached) * PREFIX_DEFAULT_CACHEABLE_SHARE
            monthly_savings = _run_rate(cacheable_tokens * rate_delta, now)
            if monthly_savings <= 0:
                continue
            # When the replay corpus holds this route's prompts, replace generic
            # advice with a deterministic proposal: where the volatile span sits
            # and what moving it unlocks. Metrics only; no text persists.
            proposal = propose_prefix_restructure(db, project, row.model)
            description = (
                f"{target} sends ~{avg_input:,.0f} input tokens per call across {requests} calls, but only "
                f"{dominant_share * 100:.0f}% of {samples} fingerprinted requests share a stable prefix, so "
                f"provider prompt caching cannot engage. "
            )
            if proposal is not None:
                description += (
                    f"Analysis of {proposal.sample_count} captured prompts: the first "
                    f"{proposal.stable_prefix_chars:,} characters are identical on every request, then a volatile "
                    f"span of ~{proposal.volatile_span_min_chars:,}-{proposal.volatile_span_max_chars:,} characters "
                    f"begins at offset {proposal.volatile_span_offset:,}. Moving that span to the end of the "
                    f"system message makes {proposal.projected_stable_share * 100:.0f}% of the prompt byte-stable "
                    f"and unlocks {row.model}'s cache-read rate."
                )
            else:
                description += (
                    "Move volatile content (timestamps, per-user data) out of the leading system/tool block "
                    f"to unlock {row.model}'s cache-read rate."
                )
            _upsert(
                db,
                project,
                RecommendationSeed(
                    dedupe_key=f"prompt_prefix_restructure:{_route_key(row.request_type, row.feature)}:{row.model}:{now:%Y-%m}",
                    type="prompt_prefix_restructure",
                    lever="semantic_cache",
                    title=f"Stabilize the prompt prefix for {target}",
                    description=description,
                    details=proposal.as_details() if proposal is not None else None,
                    rationale=(
                        "Measured prefix stability is too low for a provider prompt cache to key on; the discount is "
                        "forfeited on every call until the prefix stops changing."
                    ),
                    estimated_monthly_savings_usd=monthly_savings,
                    monthly_request_volume=requests,
                    risk_level="low",
                    confidence="medium",
                    target_type="route",
                    target_key=_route_key(row.request_type, row.feature),
                    related_provider=row.provider,
                    related_model=row.model,
                    related_feature=row.feature,
                ),
            )
            return

        if measured and dominant_share >= PREFIX_STABLE_SHARE:
            cacheable_share = Decimal(str(round(dominant_share, 4)))
            share_basis = (
                f"a measured {dominant_share * 100:.0f}% of {samples} fingerprinted requests share one stable prefix"
            )
        else:
            cacheable_share = PREFIX_DEFAULT_CACHEABLE_SHARE
            share_basis = "conservatively assuming half the uncached input is a stable prefix"
        cacheable_tokens = Decimal(input_tokens - cached) * cacheable_share
        monthly_savings = _run_rate(cacheable_tokens * rate_delta, now)
        if monthly_savings <= 0:
            continue
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"prompt_cache:{_route_key(row.request_type, row.feature)}:{row.model}:{now:%Y-%m}",
                type="prompt_cache",
                lever="semantic_cache",
                title=f"Enable prompt caching for {target}",
                description=(
                    f"{target} sends ~{avg_input:,.0f} input tokens per call across {requests} calls at a "
                    f"{hit_rate * 100:.0f}% cache hit rate. Cache the stable prompt prefix so it bills at "
                    f"{row.model}'s cache-read rate ({share_basis})."
                ),
                rationale="Large, repeated input prompts with a low cache hit rate are billed at full input price; the cache-read rate is materially cheaper.",
                estimated_monthly_savings_usd=monthly_savings,
                monthly_request_volume=requests,
                risk_level="low",
                confidence="high" if measured and dominant_share >= PREFIX_STABLE_SHARE else "medium",
                target_type="route",
                target_key=_route_key(row.request_type, row.feature),
                related_provider=row.provider,
                related_model=row.model,
                related_feature=row.feature,
            ),
        )
        return


def _add_semantic_cache_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    cache_key = UsageEvent.event_metadata["semantic_cache_key"].astext
    rows = db.execute(
        select(
            cache_key.label("cache_key"),
            UsageEvent.request_type,
            UsageEvent.feature,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
        )
        .where(
            UsageEvent.project_id == project.id,
            UsageEvent.received_at >= start,
            cache_key.is_not(None),
        )
        .group_by(cache_key, UsageEvent.request_type, UsageEvent.feature)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    if rows is None or int(rows.requests or 0) < 3:
        return
    spend = _money(rows.spend)
    if spend <= 0:
        return
    target = _target_name(rows.request_type, rows.feature)
    _upsert(
        db,
        project,
        RecommendationSeed(
            dedupe_key=f"semantic_cache:{rows.cache_key}:{now:%Y-%m}",
            type="semantic_cache",
            lever="semantic_cache",
            title=f"Cache repeated requests for {target}",
            description=f"{rows.requests} requests share semantic cache key '{rows.cache_key}'. Add a semantic cache policy for this workload.",
            rationale="Repeated semantic cache keys indicate avoidable full model calls.",
            estimated_monthly_savings_usd=_run_rate(spend * Decimal("0.50"), now),
            monthly_request_volume=int(rows.requests or 0),
            risk_level="low",
            confidence="medium",
            target_type="route",
            target_key=_route_key(rows.request_type, rows.feature),
            related_feature=rows.feature,
        ),
    )


def _add_batching_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    batchable = UsageEvent.event_metadata["batchable"].astext.in_(("true", "1", "yes"))
    rows = db.execute(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.request_type,
            UsageEvent.feature,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        )
        .where(
            UsageEvent.project_id == project.id,
            UsageEvent.received_at >= start,
            or_(
                batchable,
                UsageEvent.request_type.ilike("%batch%"),
                UsageEvent.request_type.ilike("%background%"),
                UsageEvent.request_type.ilike("%export%"),
                UsageEvent.request_type.ilike("%sync%"),
            ),
        )
        .group_by(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.request_type,
            UsageEvent.feature,
        )
        .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0).desc())
        .limit(10)
    )
    for row in rows:
        price = _latest_price(db, row.model, row.provider)
        if price is None or price.input_cost_per_token_batch is None or price.output_cost_per_token_batch is None:
            continue
        current = _priced_cost(price, int(row.input_tokens or 0), int(row.output_tokens or 0))
        batched = _priced_cost(
            price,
            int(row.input_tokens or 0),
            int(row.output_tokens or 0),
            use_batch=True,
        )
        savings = current - batched
        if savings <= 0:
            continue
        target = _target_name(row.request_type, row.feature)
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"batching:{_route_key(row.request_type, row.feature)}:{row.model}:{now:%Y-%m}",
                type="batching",
                lever="batching",
                title=f"Batch non-urgent {target} calls",
                description=f"{target} is marked batchable and {row.model} has batch pricing. Route non-urgent jobs through batch endpoints.",
                rationale="Batch pricing is available and the workload is explicitly marked non-urgent or background.",
                estimated_monthly_savings_usd=_run_rate(savings, now),
                monthly_request_volume=int(row.requests or 0),
                risk_level="low",
                confidence="high",
                target_type="route",
                target_key=_route_key(row.request_type, row.feature),
                related_provider=row.provider,
                related_model=row.model,
                related_feature=row.feature,
            ),
        )
        return


def _add_model_downshift_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    rows = db.execute(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.feature,
            UsageEvent.environment,
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(UsageEvent.provider, UsageEvent.model, UsageEvent.feature, UsageEvent.environment)
        .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0).desc())
        .limit(20)
    )
    for row in rows:
        catalog = _model_catalog(db, row.model, row.provider)
        if catalog is None or not catalog.cheaper_substitute_key:
            continue
        current_price = _latest_price(db, row.model, row.provider)
        cheaper_price = _latest_price(db, catalog.cheaper_substitute_key, row.provider)
        if current_price is None or cheaper_price is None:
            continue
        current = _priced_cost(current_price, int(row.input_tokens or 0), int(row.output_tokens or 0))
        cheaper = _priced_cost(cheaper_price, int(row.input_tokens or 0), int(row.output_tokens or 0))
        savings = (current - cheaper) * ELIGIBLE_SHARE
        if savings <= 0:
            continue
        feature = row.feature or row.model
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"{LEVER_MODEL_DOWNSHIFT}:{feature}:{row.model}:{catalog.cheaper_substitute_key}:{now:%Y-%m}",
                type=LEVER_MODEL_DOWNSHIFT,
                lever=LEVER_MODEL_DOWNSHIFT,
                title=f"Evaluate {catalog.cheaper_substitute_key} for {feature}",
                description=f"{feature} uses {row.model}. The catalog maps it to lower-cost substitute {catalog.cheaper_substitute_key}; replay/eval before applying.",
                rationale="Catalog tier metadata identifies a lower-cost workload-level substitute.",
                estimated_monthly_savings_usd=_run_rate(savings, now),
                monthly_request_volume=int(row.requests or 0),
                risk_level="medium" if row.environment in {"production", "prod"} else "low",
                confidence="medium",
                target_type="feature",
                target_key=feature,
                related_provider=row.provider,
                related_model=row.model,
                related_feature=row.feature,
                related_environment=row.environment,
            ),
        )
        return


def _add_smart_routing_recommendation(db: Session, project: Project, start: datetime, now: datetime) -> None:
    rows = list(
        db.execute(
            select(
                UsageEvent.request_type,
                UsageEvent.feature,
                UsageEvent.provider,
                UsageEvent.model,
                func.count().label("requests"),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("spend"),
            )
            .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
            .group_by(
                UsageEvent.request_type,
                UsageEvent.feature,
                UsageEvent.provider,
                UsageEvent.model,
            )
        )
    )
    by_route: dict[str, list] = {}
    for row in rows:
        by_route.setdefault(_route_key(row.request_type, row.feature), []).append(row)

    best_seed: RecommendationSeed | None = None
    best_savings = Decimal("0")
    for route, route_rows in by_route.items():
        if len(route_rows) < 2:
            continue
        priced_rows = [row for row in route_rows if _money(row.spend) > 0 and row.requests]
        if len(priced_rows) < 2:
            continue
        cheapest = min(priced_rows, key=lambda row: _money(row.spend) / Decimal(row.requests))
        expensive = max(priced_rows, key=lambda row: _money(row.spend) / Decimal(row.requests))
        cheapest_avg = _money(cheapest.spend) / Decimal(cheapest.requests)
        expensive_avg = _money(expensive.spend) / Decimal(expensive.requests)
        if expensive_avg <= cheapest_avg:
            continue
        candidate_savings = (expensive_avg - cheapest_avg) * Decimal(expensive.requests) * ELIGIBLE_SHARE
        if candidate_savings <= best_savings:
            continue
        target = _target_name(expensive.request_type, expensive.feature)
        best_savings = candidate_savings
        best_seed = RecommendationSeed(
            dedupe_key=f"smart_routing:{route}:{expensive.model}:{cheapest.model}:{now:%Y-%m}",
            type="smart_routing",
            lever="smart_routing",
            title=f"Route some {target} traffic to {cheapest.model}",
            description=f"{target} has traffic on both {expensive.model} and lower-cost {cheapest.model}. Evaluate routing policy by request risk.",
            rationale="The same route is already served by models with different cost per request, so routing policy can shift eligible traffic.",
            estimated_monthly_savings_usd=_run_rate(candidate_savings, now),
            monthly_request_volume=int(expensive.requests or 0),
            risk_level="medium",
            confidence="medium",
            target_type="route",
            target_key=route,
            related_provider=expensive.provider,
            related_model=expensive.model,
            related_feature=expensive.feature,
        )
    if best_seed is not None:
        _upsert(db, project, best_seed)


def refresh_recommendations(db: Session, project: Project) -> None:
    now = datetime.now(UTC)
    start = _month_start(now)
    cost = UsageEvent.cost_usd

    totals = db.execute(
        select(
            func.coalesce(func.sum(cost), 0).label("spend"),
            func.count().label("requests"),
            func.count().filter(UsageEvent.pricing_status != "priced").label("unpriced"),
            func.coalesce(func.sum(cost).filter(UsageEvent.success.is_(False)), 0).label("failed_spend"),
            func.count().filter(UsageEvent.success.is_(False)).label("failed_count"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        ).where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
    ).one()

    spend = _money(totals.spend)
    days_in_month = now.day
    monthly_forecast = (
        spend / Decimal(days_in_month) * Decimal(calendar.monthrange(now.year, now.month)[1])
        if days_in_month
        else Decimal("0")
    )

    if totals.unpriced:
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"unpriced:{now:%Y-%m}",
                type="unpriced_usage",
                title="Review unpriced usage",
                description=f"{totals.unpriced} events this month could not be priced from the catalog. Add model prices or an org override so spend totals are trusted.",
                estimated_monthly_savings_usd=None,
                risk_level="low",
                confidence="high",
                target_type="pricing_catalog",
                target_key="unpriced_usage",
                rationale="Pricing trust must be fixed before savings can be defended.",
            ),
        )

    budget = project.organization.monthly_spend_budget_usd
    if budget is not None and monthly_forecast > budget:
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"budget_overrun:{now:%Y-%m}",
                type="budget_overrun",
                title="Forecast is over budget",
                description=f"Current run-rate forecast is ${monthly_forecast:.2f}, above the monthly budget of ${budget:.2f}. Review top spend drivers and reduce low-value usage.",
                estimated_monthly_savings_usd=monthly_forecast - budget,
                risk_level="medium",
                confidence="medium",
                target_type="budget",
                target_key="monthly_spend_budget",
                rationale="Budget variance is an input to the decision queue until automated controls exist.",
            ),
        )

    env_rows = db.execute(
        select(
            UsageEvent.environment,
            func.coalesce(func.sum(cost), 0).label("spend"),
        )
        .where(UsageEvent.project_id == project.id, UsageEvent.received_at >= start)
        .group_by(UsageEvent.environment)
    )
    for row in env_rows:
        env = row.environment or "unknown"
        env_spend = _money(row.spend)
        if env not in {"production", "prod"} and env_spend > 0:
            _upsert(
                db,
                project,
                RecommendationSeed(
                    dedupe_key=f"nonprod:{env}:{now:%Y-%m}",
                    type="non_production_spend",
                    title=f"Review {env} AI spend",
                    description=f"{env} usage has spent ${env_spend:.2f} this month. Add a budget cap or investigate runaway non-production calls.",
                    estimated_monthly_savings_usd=env_spend,
                    risk_level="low",
                    confidence="medium",
                    target_type="environment",
                    target_key=env,
                    rationale="Non-production spend is usually safer to cap or pause than production traffic.",
                    related_environment=env,
                ),
            )

    if totals.failed_count and _money(totals.failed_spend) > 0:
        _upsert(
            db,
            project,
            RecommendationSeed(
                dedupe_key=f"failed_spend:{now:%Y-%m}",
                type="failed_request_spend",
                title="Investigate failed request spend",
                description=f"{totals.failed_count} failed requests consumed billable tokens this month. Review retries, provider errors, and validation failures.",
                estimated_monthly_savings_usd=_money(totals.failed_spend),
                risk_level="low",
                confidence="medium",
                target_type="request_health",
                target_key="failed_requests",
                rationale="Failed requests can consume billable tokens without creating customer value.",
            ),
        )

    _add_token_trim_recommendation(db, project, start, now, spend)
    _add_prompt_cache_recommendation(db, project, start, now)
    _add_agent_loop_recommendation(db, project, start, now)
    _add_semantic_cache_recommendation(db, project, start, now)
    _add_batching_recommendation(db, project, start, now)
    _add_model_downshift_recommendation(db, project, start, now)
    _add_smart_routing_recommendation(db, project, start, now)


def ensure_recommendations_fresh(db: Session, project: Project, now: datetime | None = None) -> bool:
    """Recompute recommendations only when the stored set is stale, so a read
    endpoint serves existing rows instead of scanning a month of usage on every
    request. Returns True if a recompute happened.

    The recompute still writes (it upserts recommendation rows), but the staleness
    gate bounds that to at most once per project per window. Concurrent stale reads
    may both recompute; the upserts are idempotent, so the cost is a little
    duplicate work, never duplicate or corrupt recommendations.
    """
    now = now or datetime.now(UTC)
    max_age = timedelta(seconds=settings.recommendations_max_age_seconds)
    last = project.recommendations_refreshed_at
    if last is not None and now - last < max_age:
        return False
    refresh_recommendations(db, project)
    project.recommendations_refreshed_at = now
    db.add(project)
    db.commit()
    return True
