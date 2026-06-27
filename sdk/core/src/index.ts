/** @varsten/core — the provider-agnostic fail-open engine.
 *
 * Internal in v1: consumed by @varsten/openai, @varsten/anthropic, and
 * @varsten/gemini, not published on its own. It owns the one copy of the fallback
 * decision, the local circuit breaker, the error taxonomy, and best-effort
 * telemetry, so every provider wrapper behaves identically and the safety-critical
 * logic is audited in exactly one place.
 */

export { LocalBreaker } from "./breaker.js";
export {
  classifyError,
  genericAdapter,
  makeStainlessAdapter,
  readHeader,
  type FallbackDecision,
  type ProviderErrorAdapter,
} from "./classify.js";
export { annotate, executeWithFallback, type CreateFn, type ExecuteParams } from "./execute.js";
export { makeTelemetryEmitter } from "./telemetry.js";
export { varstenHost } from "./url.js";
export {
  VarstenUnavailableError,
  type FallbackEvent,
  type FallbackMode,
  type FallbackPhase,
  type VarstenClientOptions,
  type VarstenMeta,
  type VarstenTimeouts,
} from "./types.js";
