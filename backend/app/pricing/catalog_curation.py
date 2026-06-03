"""Curated model tier and cheaper-substitute mapping.

The public pricing feed carries prices and capability flags but no judgment about
which model is a coarse tier or a safe cheaper substitute for which. That
judgment is curated here as reference data (not logic) and applied to
model_catalog during a sync. Keys are model_key values as they appear in the
feed; substitutes point to another model_key the engine can price and compare.

Curation is conservative on purpose: a substitute is only listed where the
cheaper model is a credible drop-in for general workloads on the same provider.
The eval/replay gate (later) is what proves a swap is safe per route; this map
only seeds the candidate so the cheaper-model lever has something to evaluate.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelCatalog

# model_key -> coarse capability tier: frontier | mid | small.
TIERS: dict[str, str] = {
    # OpenAI
    "gpt-4o": "frontier",
    "gpt-4o-2024-11-20": "frontier",
    "gpt-4o-2024-08-06": "frontier",
    "gpt-4o-mini": "small",
    "gpt-4-turbo": "frontier",
    "gpt-4": "frontier",
    "o1": "frontier",
    "o1-mini": "mid",
    "o3-mini": "mid",
    # Anthropic
    "claude-3-5-sonnet-latest": "frontier",
    "claude-3-5-sonnet-20241022": "frontier",
    "claude-3-opus-latest": "frontier",
    "claude-3-5-haiku-latest": "small",
    "claude-3-haiku-20240307": "small",
    # Google
    "gemini-1.5-pro": "frontier",
    "gemini-1.5-flash": "small",
    "gemini-1.5-flash-8b": "small",
}

# model_key -> a cheaper substitute model_key on the same provider that is a
# credible candidate for general traffic. The engine prices both and only
# surfaces the swap when it actually costs less.
SUBSTITUTES: dict[str, str] = {
    # OpenAI
    "gpt-4o": "gpt-4o-mini",
    "gpt-4o-2024-11-20": "gpt-4o-mini",
    "gpt-4o-2024-08-06": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4o",
    "gpt-4": "gpt-4o",
    "o1": "o1-mini",
    # Anthropic
    "claude-3-5-sonnet-latest": "claude-3-5-haiku-latest",
    "claude-3-5-sonnet-20241022": "claude-3-5-haiku-latest",
    "claude-3-opus-latest": "claude-3-5-sonnet-latest",
    # Google
    "gemini-1.5-pro": "gemini-1.5-flash",
}


def apply_curation(db: Session) -> int:
    """Set tier and cheaper_substitute_key on catalog rows from the curated maps.
    Returns the number of fields changed. No-ops for models not in the maps."""
    changed = 0
    for model_key, tier in TIERS.items():
        for catalog in db.scalars(
            select(ModelCatalog).where(ModelCatalog.model_key == model_key)
        ):
            if catalog.tier != tier:
                catalog.tier = tier
                changed += 1
    for model_key, substitute in SUBSTITUTES.items():
        for catalog in db.scalars(
            select(ModelCatalog).where(ModelCatalog.model_key == model_key)
        ):
            if catalog.cheaper_substitute_key != substitute:
                catalog.cheaper_substitute_key = substitute
                changed += 1
    return changed
