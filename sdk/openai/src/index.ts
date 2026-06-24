export { VarstenOpenAI } from "./client.js";
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
