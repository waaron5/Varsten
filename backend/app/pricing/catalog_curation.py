"""Curated model tier and cheaper-substitute mapping.

The public pricing feed carries prices and capability flags but no judgment about
which model is a coarse tier or a safe lower-cost substitute for which. That
judgment is curated here as reference data (not logic) and applied to
model_catalog during a sync. Keys are model_key values as they appear in the
feed; substitutes point to another model_key the engine can price and compare.

Curation is conservative on purpose: a substitute is only listed where the
model downshift is a credible drop-in for general workloads on the same provider.
The eval/replay gate (later) is what proves a swap is safe per route; this map
only seeds the candidate so the model-downshift lever has something to evaluate.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelCatalog

# model_key -> coarse capability tier: frontier | mid | small. Keys are the
# clean direct-provider names confirmed present and priced in the feed.
TIERS: dict[str, str] = {
    # OpenAI
    "gpt-4o": "frontier",
    "gpt-4o-mini": "small",
    "gpt-4-turbo": "frontier",
    "gpt-4": "frontier",
    "o1": "frontier",
    "o3-mini": "mid",
    # Anthropic
    "claude-3-5-sonnet": "frontier",
    "claude-3-opus-20240229": "frontier",
    "claude-3-haiku": "small",
    # Google
    "gemini/gemini-1.5-flash": "small",
}

# model_key -> a lower-cost substitute model_key, a credible candidate for general
# traffic. Both the key and its substitute are confirmed priced, so the engine
# can compare them; it only surfaces the swap when it actually costs less.
SUBSTITUTES: dict[str, str] = {
    # OpenAI
    "gpt-4o": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4o",
    "gpt-4": "gpt-4o",
    "o1": "o3-mini",
    # Anthropic
    "claude-3-5-sonnet": "claude-3-haiku",
    "claude-3-opus-20240229": "claude-3-5-sonnet",
}


def apply_curation(db: Session) -> int:
    """Set tier and cheaper_substitute_key on catalog rows from the curated maps.
    Returns the number of fields changed. No-ops for models not in the maps."""
    changed = 0
    for model_key, tier in TIERS.items():
        for catalog in db.scalars(select(ModelCatalog).where(ModelCatalog.model_key == model_key)):
            if catalog.tier != tier:
                catalog.tier = tier
                changed += 1
    for model_key, substitute in SUBSTITUTES.items():
        for catalog in db.scalars(select(ModelCatalog).where(ModelCatalog.model_key == model_key)):
            if catalog.cheaper_substitute_key != substitute:
                catalog.cheaper_substitute_key = substitute
                changed += 1
    return changed
