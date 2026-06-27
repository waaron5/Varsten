import { randomUUID } from "node:crypto";

import {
  classifyError,
  genericAdapter,
  type ProviderErrorAdapter,
} from "./classify.js";
import { LocalBreaker } from "./breaker.js";
import {
  type FallbackEvent,
  type FallbackMode,
  type FallbackPhase,
  type VarstenMeta,
  VarstenUnavailableError,
} from "./types.js";

/** Attach a non-enumerable `_varsten` marker so callers can inspect how a response
 * was served without it appearing in JSON.stringify or breaking shapes. */
export function annotate<T>(res: T, servedBy: VarstenMeta["servedBy"], reason?: string): T {
  if (res && typeof res === "object") {
    try {
      Object.defineProperty(res, "_varsten", {
        value: { servedBy, reason } satisfies VarstenMeta,
        enumerable: false,
        writable: false,
        configurable: true,
      });
    } catch {
      // Some response objects (e.g. a frozen stream) are non-extensible; the marker
      // is best-effort and must never break the response.
    }
  }
  return res;
}

export type CreateFn = (body: any, idempotencyKey: string) => Promise<any>;

export interface ExecuteParams {
  body: any;
  mode: FallbackMode;
  primaryCreate: CreateFn;
  /** null when no provider key is configured (fallback impossible). */
  fallbackCreate: CreateFn | null;
  breaker: LocalBreaker;
  fallbackOnReadTimeout: boolean;
  sdkVersion: string;
  /** The upstream provider, stamped onto fallback events for per-provider telemetry. */
  provider?: string;
  /** Reads provider-specific signals off a thrown error. Defaults to the generic
   * fetch/stainless adapter; provider wrappers inject one that knows their SDK. */
  errorAdapter?: ProviderErrorAdapter;
  /** A streaming request. Fallback can only happen before the stream is returned
   * (pre-first-token); a stream that has started failing mid-iteration is the
   * caller's to surface, never restarted. */
  streaming?: boolean;
  onFallback?: (event: FallbackEvent) => void;
  emitTelemetry?: (event: FallbackEvent) => void;
}

/** Run the optimized Varsten attempt, falling back to the provider per the
 * contract. Pure orchestration: the two create functions, the breaker, and the
 * error adapter are injected, so this is unit-tested without a network and reused
 * verbatim by every provider wrapper. */
export async function executeWithFallback(params: ExecuteParams): Promise<any> {
  const adapter = params.errorAdapter ?? genericAdapter;
  const model = (params.body && params.body.model) || "";
  const start = Date.now();
  // One idempotency key per logical request, sent on BOTH the Varsten attempt and
  // the direct fallback. If Varsten forwarded the (verbatim) request to the provider
  // before failing, the provider can dedupe the direct retry against it, so the
  // read-timeout fallback window cannot double-charge or double-generate.
  const idempotencyKey = `varsten-${randomUUID()}`;
  // For a stream, a fallback can only occur before the stream object is returned
  // (the optimized create() rejected), i.e. before any token reached the caller.
  const fallbackPhase: FallbackPhase = params.streaming ? "pre-first-token" : "pre-request";

  const doFallback = async (
    reasonCode: string,
    varstenStatus: number | undefined,
    phase: FallbackPhase,
    requestId?: string,
  ): Promise<any> => {
    if (!params.fallbackCreate) {
      throw new VarstenUnavailableError(reasonCode, varstenStatus);
    }
    const res = await params.fallbackCreate(params.body, idempotencyKey);
    annotate(res, "provider-fallback", reasonCode);
    const event: FallbackEvent = {
      requestId,
      reasonCode,
      varstenStatus,
      phase,
      model,
      latencyMs: Date.now() - start,
      sdkVersion: params.sdkVersion,
      provider: params.provider,
    };
    safeCall(params.onFallback, event);
    safeCall(params.emitTelemetry, event);
    return res;
  };

  // Fallback disabled: straight through, no safety net (errors propagate).
  if (params.mode === "off") {
    return params.primaryCreate(params.body, idempotencyKey);
  }

  // Breaker open: skip Varsten entirely and go direct.
  if (!params.breaker.allow()) {
    return doFallback("breaker_open", undefined, fallbackPhase);
  }

  try {
    const res = await params.primaryCreate(params.body, idempotencyKey);
    params.breaker.recordSuccess();
    return annotate(res, "varsten");
  } catch (err: any) {
    const decision = classifyError(err, { fallbackOnReadTimeout: params.fallbackOnReadTimeout }, adapter);
    if (!decision.fallback) {
      throw err;
    }
    params.breaker.recordVarstenFailure();
    const requestId = adapter.requestId(err);
    return doFallback(decision.reasonCode, decision.varstenStatus, fallbackPhase, requestId);
  }
}

function safeCall<A>(fn: ((arg: A) => void) | undefined, arg: A): void {
  if (!fn) return;
  try {
    fn(arg);
  } catch {
    // A telemetry/callback error must never affect the request result.
  }
}
