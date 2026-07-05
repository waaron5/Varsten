import OpenAI from "openai";

import { LocalBreaker } from "./breaker.js";
import { executeWithFallback } from "./fallback.js";
import { makeTelemetryEmitter } from "./telemetry.js";
import {
  SDK_VERSION,
  metadataHeaderValue,
  VARSTEN_METADATA_HEADER,
  type FallbackEvent,
  type VarstenOptions,
  type VarstenRequestMetadata,
} from "./types.js";

/** Per-request options: `varsten` carries workflow metadata (trace id, feature,
 * task hints). Sent to Varsten only; the direct provider fallback never sees it. */
export interface VarstenRequestOptions {
  varsten?: VarstenRequestMetadata;
}

const DEFAULT_BASE_URL = "https://api.varsten.ai/v1";
const DEFAULT_VARSTEN_TOTAL_MS = 60_000;

/**
 * A drop-in, fail-open wrapper around the OpenAI client.
 *
 * Calls flow through Varsten (optimized) by default. If Varsten is unreachable,
 * returns a Varsten-originated error, or trips the local breaker, the same request
 * is reissued directly to the provider with the local provider key. The optimized
 * and direct clients are both stock `OpenAI` instances, so behavior, streaming
 * parsing, and tool-call shapes are exactly the provider SDK's.
 *
 * Surface mirrors the OpenAI SDK: `client.chat.completions.create(...)`.
 *
 * Streaming note: in this version a streaming request goes through Varsten without
 * the direct-fallback safety net (streaming fail-open lands in the next version).
 */
export class VarstenOpenAI {
  readonly chat: {
    completions: { create: (body: any, options?: VarstenRequestOptions) => Promise<any> };
  };

  private readonly primary: OpenAI;
  private readonly fallbackClient: OpenAI | null;
  private readonly options: Required<Pick<VarstenOptions, "fallback" | "fallbackOnReadTimeout">> & {
    onFallback?: (e: FallbackEvent) => void;
  };
  private readonly breaker: LocalBreaker;
  private readonly emitTelemetry: (event: FallbackEvent) => void;

  constructor(opts: VarstenOptions = {}) {
    const varstenApiKey = opts.varstenApiKey ?? process.env.VARSTEN_API_KEY;
    const providerApiKey = opts.openaiApiKey ?? process.env.OPENAI_API_KEY;
    const baseURL = opts.baseURL ?? process.env.VARSTEN_BASE_URL ?? DEFAULT_BASE_URL;

    if (!varstenApiKey) {
      throw new Error("varstenApiKey is required (or set VARSTEN_API_KEY).");
    }

    const varstenTotalMs = opts.timeouts?.varstenTotalMs ?? DEFAULT_VARSTEN_TOTAL_MS;
    const providerTotalMs = opts.timeouts?.providerTotalMs;

    // Optimized path. maxRetries: 0 so the OpenAI SDK never retries Varsten itself;
    // our breaker and single direct fallback own the retry policy.
    this.primary = new OpenAI({
      apiKey: varstenApiKey,
      baseURL,
      maxRetries: 0,
      timeout: varstenTotalMs,
      // Lets Varsten record that this project's OpenAI traffic runs through the
      // fail-open SDK, powering the dashboard's per-provider coverage status. Only
      // on the optimized client; the direct fallback talks to the provider.
      defaultHeaders: { "X-Varsten-Client": SDK_VERSION },
    });

    // Direct path. Only built when a provider key is present; the provider key
    // never goes to Varsten. Keep the provider SDK's own retry behavior.
    this.fallbackClient = providerApiKey
      ? new OpenAI({ apiKey: providerApiKey, ...(providerTotalMs ? { timeout: providerTotalMs } : {}) })
      : null;

    this.options = {
      fallback: opts.fallback ?? "auto",
      fallbackOnReadTimeout: opts.fallbackOnReadTimeout ?? false,
      onFallback: opts.onFallback,
    };
    this.breaker = new LocalBreaker(opts.breakerThreshold ?? 5, opts.breakerCooldownMs ?? 30_000);
    this.emitTelemetry = makeTelemetryEmitter({ baseURL, varstenApiKey });

    this.chat = {
      completions: { create: (body: any, options?: VarstenRequestOptions) => this.create(body, options) },
    };
  }

  private create(body: any, options?: VarstenRequestOptions): Promise<any> {
    // Workflow metadata goes to Varsten only. The direct fallback talks straight
    // to the provider, which has no business seeing workflow labels.
    const metadataValue = metadataHeaderValue(options?.varsten);
    const primaryHeaders = metadataValue ? { [VARSTEN_METADATA_HEADER]: metadataValue } : undefined;
    // Streaming flows through the same engine. The optimized create() rejects on a
    // pre-stream failure (Varsten unreachable, circuit-open, 5xx) before any token
    // reaches the caller, so the fallback there is safe; once a stream is returned,
    // any mid-iteration error surfaces to the caller and is never restarted.
    return executeWithFallback({
      body,
      mode: this.options.fallback,
      streaming: Boolean(body && body.stream),
      primaryCreate: (b, idem) =>
        this.primary.chat.completions.create(b, {
          idempotencyKey: idem,
          ...(primaryHeaders ? { headers: primaryHeaders } : {}),
        }) as Promise<any>,
      fallbackCreate: this.fallbackClient
        ? (b, idem) => this.fallbackClient!.chat.completions.create(b, { idempotencyKey: idem }) as Promise<any>
        : null,
      breaker: this.breaker,
      fallbackOnReadTimeout: this.options.fallbackOnReadTimeout,
      sdkVersion: SDK_VERSION,
      onFallback: this.options.onFallback,
      emitTelemetry: this.emitTelemetry,
    });
  }
}
