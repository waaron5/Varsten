"""Canonical savings-lever vocabulary."""

LEVER_SMART_ROUTING = "smart_routing"
LEVER_SEMANTIC_CACHE = "semantic_cache"
LEVER_TOKEN_TRIM = "token_trim"
LEVER_MODEL_DOWNSHIFT = "model_downshift"
LEVER_BATCHING = "batching"
# Learned prompt compression: an approved, eval-cleared compressed rewrite of a
# route's stable system prompt, substituted at request time by exact-hash match.
# It changes what the model reads, so it is approve-mode and eval-gated always.
LEVER_PROMPT_COMPRESSION = "prompt_compression"

LEVER_DEFAULT_AUTOMATION: tuple[tuple[str, str], ...] = (
    (LEVER_SMART_ROUTING, "approve"),
    (LEVER_SEMANTIC_CACHE, "auto"),
    (LEVER_TOKEN_TRIM, "auto"),
    (LEVER_MODEL_DOWNSHIFT, "approve"),
    (LEVER_BATCHING, "auto"),
    (LEVER_PROMPT_COMPRESSION, "approve"),
)

ROUTING_LEVERS = (LEVER_MODEL_DOWNSHIFT, LEVER_SMART_ROUTING)

LEVER_DISPLAY_ORDER = (
    LEVER_SEMANTIC_CACHE,
    LEVER_MODEL_DOWNSHIFT,
    LEVER_BATCHING,
    LEVER_TOKEN_TRIM,
    LEVER_SMART_ROUTING,
    LEVER_PROMPT_COMPRESSION,
)

LEVER_LABELS = {
    LEVER_SMART_ROUTING: "Smart routing",
    LEVER_SEMANTIC_CACHE: "Semantic cache",
    LEVER_TOKEN_TRIM: "Token trim",
    LEVER_MODEL_DOWNSHIFT: "Model downshift",
    LEVER_BATCHING: "Batching",
    LEVER_PROMPT_COMPRESSION: "Prompt compression",
}
