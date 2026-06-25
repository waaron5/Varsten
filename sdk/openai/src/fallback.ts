import { randomUUID } from "node:crypto";

import { APIConnectionError, APIConnectionTimeoutError } from "openai";

import { LocalBreaker } from "./breaker.js";
import {
  type FallbackEvent,
  type FallbackMode,
  type FallbackPhase,
  type VarstenMeta,
  VarstenUnavailableError,
} from "./types.js";

/** Varsten-origin error codes that must NOT trigger fallback. budget_exceeded is
 * a deliberate customer cap; bad_request/unauthorized are the caller's own fault.
 * Mirrors docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md. */
const VARSTEN_NO_FALLBACK_CODES = new Set(["budget_exceeded", "bad_request", "unauthorized"]);

const CONNECTION_ERRNOS = new Set(["ECONNREFUSED", "ENOTFOUND", "ECONNRESET", "EAI_AGAIN", "EPIPE"]);

export interface FallbackDecision {
  fallback: boolean;
  reasonCode: string;
  varstenStatus?: number;
}

function getHeader(headers: unknown, name: string): string | undefined {
  if (!headers) return undefined;
  const anyH = headers as { get?: (n: string) => string | null };
  if (typeof anyH.get === "function") return anyH.get(name) ?? undefined;
  const lower = name.toLowerCase();
  for (const key of Object.keys(headers as Record<string, unknown>)) {
    if (key.toLowerCase() === lower) {
      const v = (headers as Record<string, unknown>)[key];
      return v == null ? undefined : String(v);
    }
  }
  return undefined;
}

function readOrigin(err: any): string | undefined {
  return getHeader(err?.headers, "x-varsten-origin") ?? err?.error?.origin ?? undefined;
}

function readCode(err: any): string | undefined {
  return err?.code ?? err?.error?.code ?? undefined;
}

function isFailureStatus(status: number): boolean {
  return status >= 400;
}

/**
 * Decide whether a failed Varsten attempt should fall back to the provider.
 *
 * The contract (frozen): a response tagged origin=provider is never retried; a
 * Varsten-origin failure is retried unless it is a deliberate non-fallback code;
 * a header-less 5xx is treated as Varsten misbehaving; a transport failure with no
 * response falls back (a timeout only if opted in); anything else does not fall
 * back, so a bug in caller code never silently double-calls the provider.
 */
export function classifyError(err: any, opts: { fallbackOnReadTimeout: boolean }): FallbackDecision {
  // 1. A response arrived (the OpenAI SDK's APIError exposes a numeric status).
  if (err && typeof err.status === "number") {
    const status: number = err.status;
    const origin = readOrigin(err);
    const code = readCode(err);
    if (origin === "provider") {
      return { fallback: false, reasonCode: code ?? "provider_error", varstenStatus: status };
    }
    if (origin === "varsten") {
      if (code && VARSTEN_NO_FALLBACK_CODES.has(code)) {
        return { fallback: false, reasonCode: code, varstenStatus: status };
      }
      return { fallback: isFailureStatus(status), reasonCode: code ?? "varsten_error", varstenStatus: status };
    }
    // Header-less: a 5xx means Varsten itself is misbehaving -> fall back. A 4xx
    // with no origin is a client error we should surface, not retry.
    if (status >= 500) return { fallback: true, reasonCode: "varsten_5xx", varstenStatus: status };
    return { fallback: false, reasonCode: code ?? "client_error", varstenStatus: status };
  }

  // 2. No response. Tell a timeout apart from a hard connection failure.
  // The OpenAI SDK does not set `.name` on these errors (it stays "Error"), so we
  // also look at the constructor name, the message, and the cause errno, and use
  // instanceof as the authoritative signal in production.
  const nameBlob = `${String(err?.name ?? "")} ${String(err?.constructor?.name ?? "")}`;
  const message = String(err?.message ?? "");
  const errno = err?.code;
  const isTimeout =
    err instanceof APIConnectionTimeoutError ||
    /timeout/i.test(nameBlob) ||
    /timed?\s?out/i.test(message) ||
    errno === "ETIMEDOUT" ||
    errno === "ESOCKETTIMEDOUT";
  if (isTimeout) {
    return { fallback: opts.fallbackOnReadTimeout, reasonCode: "varsten_timeout" };
  }
  const isConnection =
    err instanceof APIConnectionError ||
    /APIConnection/i.test(nameBlob) ||
    /connection error/i.test(message) ||
    (typeof errno === "string" && CONNECTION_ERRNOS.has(errno));
  if (isConnection) {
    return { fallback: true, reasonCode: "connection_error" };
  }

  // 3. Unknown error (likely a bug, not a Varsten outage): do not fall back.
  return { fallback: false, reasonCode: "unknown_error" };
}

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
  /** A streaming request. Fallback can only happen before the stream is returned
   * (pre-first-token); a stream that has started failing mid-iteration is the
   * caller's to surface, never restarted. */
  streaming?: boolean;
  onFallback?: (event: FallbackEvent) => void;
  emitTelemetry?: (event: FallbackEvent) => void;
}

/** Run the optimized Varsten attempt, falling back to the provider per the
 * contract. Pure orchestration: the two create functions and the breaker are
 * injected, so this is unit-tested without a network. */
export async function executeWithFallback(params: ExecuteParams): Promise<any> {
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
    const decision = classifyError(err, { fallbackOnReadTimeout: params.fallbackOnReadTimeout });
    if (!decision.fallback) {
      throw err;
    }
    params.breaker.recordVarstenFailure();
    const requestId = getHeader(err?.headers, "x-varsten-request-id");
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
