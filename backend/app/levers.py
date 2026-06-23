"""Canonical savings-lever vocabulary."""

LEVER_SMART_ROUTING = "smart_routing"
LEVER_SEMANTIC_CACHE = "semantic_cache"
LEVER_TOKEN_TRIM = "token_trim"
LEVER_MODEL_DOWNSHIFT = "model_downshift"
LEVER_BATCHING = "batching"

LEVER_DEFAULT_AUTOMATION: tuple[tuple[str, str], ...] = (
    (LEVER_SMART_ROUTING, "approve"),
    (LEVER_SEMANTIC_CACHE, "auto"),
    (LEVER_TOKEN_TRIM, "auto"),
    (LEVER_MODEL_DOWNSHIFT, "approve"),
    (LEVER_BATCHING, "auto"),
)

ROUTING_LEVERS = (LEVER_MODEL_DOWNSHIFT, LEVER_SMART_ROUTING)

LEVER_DISPLAY_ORDER = (
    LEVER_SEMANTIC_CACHE,
    LEVER_MODEL_DOWNSHIFT,
    LEVER_BATCHING,
    LEVER_TOKEN_TRIM,
    LEVER_SMART_ROUTING,
)

LEVER_LABELS = {
    LEVER_SMART_ROUTING: "Smart routing",
    LEVER_SEMANTIC_CACHE: "Semantic cache",
    LEVER_TOKEN_TRIM: "Token trim",
    LEVER_MODEL_DOWNSHIFT: "Model downshift",
    LEVER_BATCHING: "Batching",
}
