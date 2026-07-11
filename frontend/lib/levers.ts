export const LEVER_SMART_ROUTING = "smart_routing";
export const LEVER_SEMANTIC_CACHE = "semantic_cache";
export const LEVER_TOKEN_TRIM = "token_trim";
export const LEVER_MODEL_DOWNSHIFT = "model_downshift";
export const LEVER_BATCHING = "batching";
export const LEVER_PROMPT_COMPRESSION = "prompt_compression";

export const ENGINE_LEVER_ORDER = [
  LEVER_SEMANTIC_CACHE,
  LEVER_MODEL_DOWNSHIFT,
  LEVER_BATCHING,
  LEVER_TOKEN_TRIM,
  LEVER_SMART_ROUTING,
  LEVER_PROMPT_COMPRESSION,
] as const;

export const LEVER_LABELS = {
  [LEVER_SMART_ROUTING]: "Smart routing",
  [LEVER_SEMANTIC_CACHE]: "Semantic cache",
  [LEVER_TOKEN_TRIM]: "Token trim",
  [LEVER_MODEL_DOWNSHIFT]: "Model downshift",
  [LEVER_BATCHING]: "Batching",
  [LEVER_PROMPT_COMPRESSION]: "Prompt compression",
} as const;
