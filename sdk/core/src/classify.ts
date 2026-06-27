/** The fallback decision: did a failed Varsten attempt originate inside Varsten
 * (safe to retry directly against the provider) or is it a faithfully relayed
 * provider result (must never be retried)?
 *
 * The contract is provider-agnostic and frozen in
 * docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md. The only provider-specific part is
 * how to read raw signals (HTTP status, the X-Varsten-Origin header, transport
 * error shape) off a given provider SDK's error object. That is isolated behind
 * `ProviderErrorAdapter`, so the decision logic below is written exactly once.
 */

/** Varsten-origin error codes that must NOT trigger fallback. budget_exceeded is
 * a deliberate customer cap; bad_request/unauthorized are the caller's own fault. */
const VARSTEN_NO_FALLBACK_CODES = new Set(["budget_exceeded", "bad_request", "unauthorized"]);

const CONNECTION_ERRNOS = new Set(["ECONNREFUSED", "ENOTFOUND", "ECONNRESET", "EAI_AGAIN", "EPIPE"]);

export interface FallbackDecision {
  fallback: boolean;
  reasonCode: string;
  varstenStatus?: number;
}

/** Reads the raw, provider-specific signals the decision needs. Every method must
 * be total and side-effect-free; a missing signal returns undefined/false. */
export interface ProviderErrorAdapter {
  /** The HTTP status, when a response actually arrived; otherwise undefined. */
  status(err: unknown): number | undefined;
  /** The X-Varsten-Origin value ("varsten" | "provider"), from header or body. */
  origin(err: unknown): string | undefined;
  /** Varsten's stable machine code (e.g. "circuit_open"), if present. */
  code(err: unknown): string | undefined;
  /** Varsten's request id, if the response carried one. */
  requestId(err: unknown): string | undefined;
  /** A transport-level timeout with no HTTP response. */
  isTimeout(err: unknown): boolean;
  /** A hard connection failure (DNS, refused, reset, TLS) with no HTTP response. */
  isConnection(err: unknown): boolean;
  /** Whether a 5xx whose origin could not be determined should be treated as
   * Varsten-originated (and thus fallback-eligible). Default true, correct for SDKs
   * that expose the X-Varsten-Origin header so a relayed provider 5xx is already
   * tagged origin=provider and excluded before this branch. Set false for an SDK
   * that cannot read response headers (Gemini's ApiError): there an unattributed
   * 5xx might be a faithfully relayed provider error, so falling back would risk a
   * double-bill. Such an SDK still falls back on any positively Varsten-attributed
   * error (body origin=varsten) and on all transport failures. */
  headerlessServerErrorIsVarsten?: boolean;
}

/** Case-insensitive header read for either a Headers-like object (has `.get`) or a
 * plain record, matching what fetch-based provider SDKs expose. */
export function readHeader(headers: unknown, name: string): string | undefined {
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

/** The default adapter for fetch/stainless-style SDKs (OpenAI, Anthropic): the
 * error exposes a numeric `.status` and a `.headers` map on an HTTP response, and
 * a `{ error: { code, origin } }` body. Transport errors are detected by name,
 * message, and Node errno. A provider package can wrap this with `instanceof`
 * checks (see makeStainlessAdapter) or replace it entirely (Gemini). */
export const genericAdapter: ProviderErrorAdapter = {
  status(err) {
    const e = err as { status?: unknown };
    return typeof e?.status === "number" ? e.status : undefined;
  },
  origin(err) {
    const e = err as { headers?: unknown; error?: { origin?: string } };
    return readHeader(e?.headers, "x-varsten-origin") ?? e?.error?.origin ?? undefined;
  },
  code(err) {
    const e = err as { code?: string; error?: { code?: string } };
    return e?.code ?? e?.error?.code ?? undefined;
  },
  requestId(err) {
    const e = err as { headers?: unknown };
    return readHeader(e?.headers, "x-varsten-request-id");
  },
  isTimeout(err) {
    return matchesTimeout(err);
  },
  isConnection(err) {
    return matchesConnection(err);
  },
};

interface SdkErrorClasses {
  APIConnectionError?: Function;
  APIConnectionTimeoutError?: Function;
}

/** genericAdapter plus authoritative `instanceof` transport detection for SDKs
 * that ship `APIConnectionError` / `APIConnectionTimeoutError` (OpenAI, Anthropic).
 * In production these classes are the reliable signal; the name/message/errno
 * heuristics remain as a fallback for mocked or wrapped errors. */
export function makeStainlessAdapter(classes: SdkErrorClasses): ProviderErrorAdapter {
  return {
    ...genericAdapter,
    isTimeout(err) {
      if (classes.APIConnectionTimeoutError && err instanceof classes.APIConnectionTimeoutError) return true;
      return matchesTimeout(err);
    },
    isConnection(err) {
      if (classes.APIConnectionError && err instanceof classes.APIConnectionError) return true;
      return matchesConnection(err);
    },
  };
}

function matchesTimeout(err: unknown): boolean {
  const e = err as { name?: string; constructor?: { name?: string }; message?: string; code?: string };
  const nameBlob = `${String(e?.name ?? "")} ${String(e?.constructor?.name ?? "")}`;
  const message = String(e?.message ?? "");
  const errno = e?.code;
  return (
    /timeout/i.test(nameBlob) ||
    /timed?\s?out/i.test(message) ||
    errno === "ETIMEDOUT" ||
    errno === "ESOCKETTIMEDOUT"
  );
}

function matchesConnection(err: unknown): boolean {
  const e = err as { name?: string; constructor?: { name?: string }; message?: string; code?: string };
  const nameBlob = `${String(e?.name ?? "")} ${String(e?.constructor?.name ?? "")}`;
  const message = String(e?.message ?? "");
  const errno = e?.code;
  return (
    /APIConnection/i.test(nameBlob) ||
    /connection error/i.test(message) ||
    (typeof errno === "string" && CONNECTION_ERRNOS.has(errno))
  );
}

function isFailureStatus(status: number): boolean {
  return status >= 400;
}

/**
 * Decide whether a failed Varsten attempt should fall back to the provider.
 *
 * Frozen contract: a response tagged origin=provider is never retried; a
 * Varsten-origin failure is retried unless it is a deliberate non-fallback code;
 * a header-less 5xx is treated as Varsten misbehaving; a transport failure with no
 * response falls back (a timeout only if opted in); anything else does not fall
 * back, so a bug in caller code never silently double-calls the provider.
 */
export function classifyError(
  err: unknown,
  opts: { fallbackOnReadTimeout: boolean },
  adapter: ProviderErrorAdapter = genericAdapter,
): FallbackDecision {
  // 1. A response arrived (the SDK's API error exposes a numeric status).
  const status = adapter.status(err);
  if (typeof status === "number") {
    const origin = adapter.origin(err);
    const code = adapter.code(err);
    if (origin === "provider") {
      return { fallback: false, reasonCode: code ?? "provider_error", varstenStatus: status };
    }
    if (origin === "varsten") {
      if (code && VARSTEN_NO_FALLBACK_CODES.has(code)) {
        return { fallback: false, reasonCode: code, varstenStatus: status };
      }
      return { fallback: isFailureStatus(status), reasonCode: code ?? "varsten_error", varstenStatus: status };
    }
    // Origin undetermined: a 5xx usually means Varsten itself is misbehaving -> fall
    // back. The exception is an SDK that cannot read the origin header (Gemini),
    // where an unattributed 5xx could be a relayed provider error; that adapter opts
    // out and the error is surfaced rather than risk a double-bill. A 4xx with no
    // origin is a client error we should surface, not retry.
    if (status >= 500) {
      const treatAsVarsten = adapter.headerlessServerErrorIsVarsten !== false;
      return {
        fallback: treatAsVarsten,
        reasonCode: treatAsVarsten ? "varsten_5xx" : "unattributed_5xx",
        varstenStatus: status,
      };
    }
    return { fallback: false, reasonCode: code ?? "client_error", varstenStatus: status };
  }

  // 2. No response. Tell a timeout apart from a hard connection failure.
  if (adapter.isTimeout(err)) {
    return { fallback: opts.fallbackOnReadTimeout, reasonCode: "varsten_timeout" };
  }
  if (adapter.isConnection(err)) {
    return { fallback: true, reasonCode: "connection_error" };
  }

  // 3. Unknown error (likely a bug, not a Varsten outage): do not fall back.
  return { fallback: false, reasonCode: "unknown_error" };
}
