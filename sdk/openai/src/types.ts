export const SDK_VERSION = "0.1.0";

/** Whether the SDK may fall back to the provider directly. */
export type FallbackMode = "auto" | "off";

/** Where in the request lifecycle a fallback happened. Non-streaming is always
 * "pre-request"; the streaming phases land in a later version. */
export type FallbackPhase = "pre-request" | "pre-first-token" | "post-first-token";

/** Emitted (synchronously, in-process) whenever the SDK serves a request by
 * calling the provider directly instead of going through Varsten. Carries only
 * metadata, never prompt or completion content. */
export interface FallbackEvent {
  /** Varsten's request id, if a response carrying one arrived. */
  requestId?: string;
  /** Stable reason the SDK fell back (e.g. "connection_error", "circuit_open"). */
  reasonCode: string;
  /** Varsten's HTTP status, if a response arrived. */
  varstenStatus?: number;
  phase: FallbackPhase;
  model: string;
  latencyMs: number;
  sdkVersion: string;
}

export interface VarstenTimeouts {
  /** Reserved for the streaming first-byte budget (later version). */
  connectMs?: number;
  /** Total budget for the Varsten (optimized) attempt. */
  varstenTotalMs?: number;
  /** Total budget for the direct provider fallback attempt. */
  providerTotalMs?: number;
}

export interface VarstenOptions {
  /** The vk_ key. Sent to Varsten only. Falls back to process.env.VARSTEN_API_KEY. */
  varstenApiKey?: string;
  /** The provider key. Stays local; used only on direct fallback. Falls back to
   * process.env.OPENAI_API_KEY. */
  openaiApiKey?: string;
  /** Varsten proxy base URL. Defaults to process.env.VARSTEN_BASE_URL or the
   * public endpoint. */
  baseURL?: string;
  /** "auto" (default) enables direct-to-provider fallback; "off" disables it. */
  fallback?: FallbackMode;
  /** Fall back when the Varsten attempt times out mid-read. Default false: a slow
   * read is usually slow generation, and retrying direct risks a double charge. */
  fallbackOnReadTimeout?: boolean;
  /** Synchronous, in-process notification on every fallback. Keep it fast. */
  onFallback?: (event: FallbackEvent) => void;
  timeouts?: VarstenTimeouts;
  /** Local circuit breaker: open after this many consecutive Varsten failures. */
  breakerThreshold?: number;
  /** How long the local breaker stays open before probing Varsten again (ms). */
  breakerCooldownMs?: number;
}

/** Attached as a non-enumerable `_varsten` property on every response so callers
 * can see how it was served without it leaking into serialization. */
export interface VarstenMeta {
  servedBy: "varsten" | "provider-fallback";
  reason?: string;
}

/** Thrown when Varsten is unavailable and no provider key is configured, so the
 * SDK cannot fall back. */
export class VarstenUnavailableError extends Error {
  readonly reasonCode: string;
  readonly varstenStatus?: number;
  constructor(reasonCode: string, varstenStatus?: number) {
    super(
      `Varsten is unavailable (${reasonCode}) and no provider key is configured for fallback. ` +
        "Set openaiApiKey (or OPENAI_API_KEY) to enable direct-to-provider fallback.",
    );
    this.name = "VarstenUnavailableError";
    this.reasonCode = reasonCode;
    this.varstenStatus = varstenStatus;
  }
}
