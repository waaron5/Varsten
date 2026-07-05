import Anthropic from "@anthropic-ai/sdk";

import {
  LocalBreaker,
  executeWithFallback,
  makeTelemetryEmitter,
  varstenHost,
  type FallbackEvent,
} from "@varsten/core";

import { anthropicErrorAdapter } from "./errors.js";
import {
  PROVIDER,
  SDK_VERSION,
  metadataHeaderValue,
  VARSTEN_METADATA_HEADER,
  type VarstenAnthropicOptions,
  type VarstenRequestMetadata,
} from "./types.js";

const DEFAULT_HOST = "https://api.varsten.ai";
const DEFAULT_VARSTEN_TOTAL_MS = 60_000;

/**
 * A drop-in, fail-open wrapper around the Anthropic client.
 *
 * Calls flow through Varsten (optimized) by default. If Varsten is unreachable,
 * returns a Varsten-originated error, or trips the local breaker, the same request
 * is reissued directly to Anthropic with the local provider key. The optimized and
 * direct clients are both stock `Anthropic` instances, so behavior, streaming
 * parsing, and tool-use shapes are exactly the provider SDK's.
 *
 * Surface mirrors the Anthropic SDK: `client.messages.create(...)`.
 *
 * The optimized client targets Varsten's host root (the Anthropic SDK appends
 * `/v1/messages`) and authenticates with the `vk_` key via `x-api-key`, which the
 * proxy accepts for the Anthropic dialect. The provider key is only ever given to
 * the direct fallback client and never sent to Varsten.
 *
 * Streaming note: in this version a streaming request goes through Varsten without
 * the direct-fallback safety net once tokens start (streaming fail-open lands in
 * the next version); a pre-stream failure still falls back cleanly.
 */
export class VarstenAnthropic {
  readonly messages: {
    create: (body: any, options?: Record<string, any>) => Promise<any>;
  };

  private readonly primary: Anthropic;
  private readonly fallbackClient: Anthropic | null;
  private readonly options: {
    fallback: "auto" | "off";
    fallbackOnReadTimeout: boolean;
    onFallback?: (e: FallbackEvent) => void;
  };
  private readonly breaker: LocalBreaker;
  private readonly emitTelemetry: (event: FallbackEvent) => void;

  constructor(opts: VarstenAnthropicOptions = {}) {
    const varstenApiKey = opts.varstenApiKey ?? process.env.VARSTEN_API_KEY;
    const providerApiKey = opts.anthropicApiKey ?? process.env.ANTHROPIC_API_KEY;
    const host = varstenHost(opts.baseURL ?? process.env.VARSTEN_BASE_URL ?? DEFAULT_HOST);

    if (!varstenApiKey) {
      throw new Error("varstenApiKey is required (or set VARSTEN_API_KEY).");
    }

    const varstenTotalMs = opts.timeouts?.varstenTotalMs ?? DEFAULT_VARSTEN_TOTAL_MS;
    const providerTotalMs = opts.timeouts?.providerTotalMs;

    // Optimized path. maxRetries: 0 so the Anthropic SDK never retries Varsten
    // itself; our breaker and single direct fallback own the retry policy.
    this.primary = new Anthropic({
      apiKey: varstenApiKey,
      baseURL: host,
      maxRetries: 0,
      timeout: varstenTotalMs,
      // Lets Varsten record that this project's Anthropic traffic runs through the
      // fail-open SDK, powering the dashboard's per-provider coverage status. Only
      // on the optimized client; the direct fallback talks to the provider.
      defaultHeaders: { "X-Varsten-Client": SDK_VERSION },
    });

    // Direct path. Only built when a provider key is present; the provider key
    // never goes to Varsten. Keep the provider SDK's own retry behavior.
    this.fallbackClient = providerApiKey
      ? new Anthropic({ apiKey: providerApiKey, ...(providerTotalMs ? { timeout: providerTotalMs } : {}) })
      : null;

    this.options = {
      fallback: opts.fallback ?? "auto",
      fallbackOnReadTimeout: opts.fallbackOnReadTimeout ?? false,
      onFallback: opts.onFallback,
    };
    this.breaker = new LocalBreaker(opts.breakerThreshold ?? 5, opts.breakerCooldownMs ?? 30_000);
    this.emitTelemetry = makeTelemetryEmitter({ baseURL: `${host}/v1`, varstenApiKey });

    this.messages = { create: (body: any, options?: Record<string, any>) => this.create(body, options) };
  }

  private create(body: any, options?: Record<string, any>): Promise<any> {
    // Workflow metadata (`options.varsten`) goes to Varsten only: the header is
    // added on the primary attempt and the field is stripped before any caller
    // options are forwarded — the direct provider fallback never sees labels.
    const { varsten, ...callerOptions } = options ?? {};
    const metadataValue = metadataHeaderValue(varsten as VarstenRequestMetadata | undefined);
    const primaryOptions = metadataValue
      ? {
          ...callerOptions,
          headers: { ...(callerOptions.headers ?? {}), [VARSTEN_METADATA_HEADER]: metadataValue },
        }
      : callerOptions;
    return executeWithFallback({
      body,
      mode: this.options.fallback,
      streaming: Boolean(body && body.stream),
      provider: PROVIDER,
      errorAdapter: anthropicErrorAdapter,
      // Our generated idempotency key wins so the direct fallback can be deduped;
      // any caller request options are preserved underneath it.
      primaryCreate: (b, idem) =>
        this.primary.messages.create(b, { ...primaryOptions, idempotencyKey: idem }) as Promise<any>,
      fallbackCreate: this.fallbackClient
        ? (b, idem) =>
            this.fallbackClient!.messages.create(b, { ...callerOptions, idempotencyKey: idem }) as Promise<any>
        : null,
      breaker: this.breaker,
      fallbackOnReadTimeout: this.options.fallbackOnReadTimeout,
      sdkVersion: SDK_VERSION,
      onFallback: this.options.onFallback,
      emitTelemetry: this.emitTelemetry,
    });
  }
}
