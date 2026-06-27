const LEVER_SMART_ROUTING = "smart_routing";
const LEVER_SEMANTIC_CACHE = "semantic_cache";
const LEVER_TOKEN_TRIM = "token_trim";
export const LEVER_MODEL_DOWNSHIFT = "model_downshift";
const LEVER_BATCHING = "batching";

export const ENGINE_LEVER_ORDER = [
  LEVER_SMART_ROUTING,
  LEVER_SEMANTIC_CACHE,
  LEVER_TOKEN_TRIM,
  LEVER_MODEL_DOWNSHIFT,
  LEVER_BATCHING,
] as const;

export const LEVER_LABELS = {
  [LEVER_SMART_ROUTING]: "Smart routing",
  [LEVER_SEMANTIC_CACHE]: "Semantic cache",
  [LEVER_TOKEN_TRIM]: "Token trim",
  [LEVER_MODEL_DOWNSHIFT]: "Model downshift",
  [LEVER_BATCHING]: "Batching",
} as const;
