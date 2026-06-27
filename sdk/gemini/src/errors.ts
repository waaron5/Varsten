import { readHeader, type ProviderErrorAdapter } from "@varsten/core";

/** Google's Gen AI SDK is not stainless-generated and behaves differently from
 * OpenAI/Anthropic in two ways that matter here:
 *
 *  1. Its thrown `ApiError` exposes only `status` and `message` — no response
 *     headers. So the X-Varsten-Origin *header* is unreadable. The SDK does set
 *     `message` to the stringified response body, and Varsten-originated errors
 *     always carry `{ error: { origin: "varsten", code } }` in that body, so a
 *     Varsten failure is still positively identifiable; a relayed provider error
 *     simply has no origin field.
 *
 *  2. Transport failures surface as a fetch `TypeError` ("fetch failed", with the
 *     real errno on `.cause`) or, on timeout, an `AbortError`.
 *
 * Because the origin header is unreadable, `headerlessServerErrorIsVarsten` is
 * false: an unattributed 5xx (possibly a faithfully relayed provider error) is
 * surfaced, not retried, so Gemini fallback never risks a double-bill. Positively
 * Varsten-attributed errors (body origin=varsten: circuit_open, rate_limited,
 * upstream_unreachable, no_provider_key, ...) and all transport failures still fall
 * back, which covers every Varsten-origin case the proxy is designed to emit.
 */

const CONNECTION_ERRNOS = new Set(["ECONNREFUSED", "ENOTFOUND", "ECONNRESET", "EAI_AGAIN", "EPIPE", "UND_ERR_CONNECT_TIMEOUT"]);

function parseBody(err: unknown): { origin?: string; code?: string; requestId?: string } {
  const message = (err as { message?: unknown })?.message;
  if (typeof message !== "string") return {};
  try {
    const parsed = JSON.parse(message) as { error?: { origin?: string; code?: string; request_id?: string } };
    const e = parsed?.error ?? {};
    return { origin: e.origin, code: e.code, requestId: e.request_id };
  } catch {
    return {};
  }
}

export const geminiErrorAdapter: ProviderErrorAdapter = {
  headerlessServerErrorIsVarsten: false,
  status(err) {
    const s = (err as { status?: unknown })?.status;
    return typeof s === "number" ? s : undefined;
  },
  origin(err) {
    return readHeader((err as { headers?: unknown })?.headers, "x-varsten-origin") ?? parseBody(err).origin;
  },
  code(err) {
    const direct = (err as { code?: string })?.code;
    return direct ?? parseBody(err).code;
  },
  requestId(err) {
    return readHeader((err as { headers?: unknown })?.headers, "x-varsten-request-id") ?? parseBody(err).requestId;
  },
  isTimeout(err) {
    const e = err as { name?: string; message?: string };
    return e?.name === "AbortError" || /aborted|timed?\s?out|timeout/i.test(String(e?.message ?? ""));
  },
  isConnection(err) {
    const e = err as { name?: string; message?: string; code?: string; cause?: { code?: string } };
    if (e?.name === "TypeError" && /fetch failed|network|terminated|fetch/i.test(String(e?.message ?? ""))) {
      return true;
    }
    const errno = e?.cause?.code ?? e?.code;
    return typeof errno === "string" && CONNECTION_ERRNOS.has(errno);
  },
};
