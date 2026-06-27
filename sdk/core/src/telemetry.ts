import type { FallbackEvent } from "./types.js";

/** The only fields the fallback telemetry endpoint accepts. Content (prompts,
 * completions, keys) is never sent; the server rejects anything else. The
 * allowlist is frozen in docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md (§7); `provider`
 * is the one additive field, so the dashboard can group fallbacks per provider. */
function toMarker(event: FallbackEvent): Record<string, unknown> {
  return {
    request_id: event.requestId,
    timestamp: new Date().toISOString(),
    reason_code: event.reasonCode,
    phase: event.phase,
    varsten_status: event.varstenStatus,
    model: event.model,
    latency_ms: event.latencyMs,
    sdk_version: event.sdkVersion,
    provider: event.provider,
  };
}

/**
 * Build a fire-and-forget telemetry emitter.
 *
 * The returned function never throws, never returns a promise the caller awaits,
 * and bounds itself with a short timeout, so reporting a fallback can never slow
 * or break the customer's actual request. A failed flush is silently dropped.
 */
export function makeTelemetryEmitter(opts: {
  baseURL: string;
  varstenApiKey?: string;
  timeoutMs?: number;
}): (event: FallbackEvent) => void {
  const url = `${opts.baseURL.replace(/\/$/, "")}/telemetry/fallback`;
  const timeoutMs = opts.timeoutMs ?? 1500;

  return (event: FallbackEvent): void => {
    if (!opts.varstenApiKey) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    void fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${opts.varstenApiKey}`,
      },
      body: JSON.stringify({ events: [toMarker(event)] }),
      signal: controller.signal,
    })
      .catch(() => {
        // best-effort; drop on any failure
      })
      .finally(() => clearTimeout(timer));
  };
}
