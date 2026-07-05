export { VarstenOpenAI, type VarstenRequestOptions } from "./client.js";
export { classifyError, executeWithFallback, annotate } from "./fallback.js";
export { LocalBreaker } from "./breaker.js";
export {
  SDK_VERSION,
  VarstenUnavailableError,
  type FallbackEvent,
  type FallbackMode,
  type FallbackPhase,
  type VarstenMeta,
  type VarstenOptions,
  type VarstenTimeouts,
} from "./types.js";
export { VarstenTrace, metadataHeaderValue, VARSTEN_METADATA_HEADER, type VarstenRequestMetadata } from "./types.js";
