import { GoogleGenAI } from "@google/genai";

import {
  LocalBreaker,
  executeWithFallback,
  makeTelemetryEmitter,
  varstenHost,
  type FallbackEvent,
} from "@varsten/core";

import { geminiErrorAdapter } from "./errors.js";
import { PROVIDER, SDK_VERSION, type VarstenGeminiOptions } from "./types.js";

const DEFAULT_HOST = "https://api.varsten.ai";
const DEFAULT_VARSTEN_TOTAL_MS = 60_000;

/** Inject the idempotency key as a request header without mutating the caller's
 * params object. Gemini has no per-call options arg, so it rides in
 * `config.httpOptions.headers`. */
function withIdempotency(params: any, idempotencyKey: string): any {
  const config = params?.config ?? {};
  const httpOptions = config.httpOptions ?? {};
  const headers = { ...(httpOptions.headers ?? {}), "Idempotency-Key": idempotencyKey };
  return { ...params, config: { ...config, httpOptions: { ...httpOptions, headers } } };
}

/**
 * A drop-in, fail-open wrapper around the Google Gen AI client.
 *
 * Calls flow through Varsten (optimized) by default. If Varsten is unreachable,
 * returns a Varsten-originated error, or trips the local breaker, the same request
 * is reissued directly to Gemini with the local provider key. The optimized and
 * direct clients are both stock `GoogleGenAI` instances, so behavior, streaming,
 * and function-call shapes are exactly the provider SDK's.
 *
 * Surface mirrors the Gen AI SDK: `client.models.generateContent(...)` and
 * `client.models.generateContentStream(...)`.
 *
 * The optimized client targets Varsten's host root (the Gen AI SDK appends
 * `/v1beta/models/{model}:generateContent`) and authenticates with the `vk_` key
 * via `x-goog-api-key`, which the proxy accepts for the Gemini dialect. The
 * provider key is only ever given to the direct fallback client and never sent to
 * Varsten.
 *
 * Idempotency: the generated key is sent only on the Varsten attempt. Google does
 * not honor an idempotency key, so attaching it to the direct fallback would add an
 * unknown header for no dedup benefit. The Gemini fallback is also conservative on
 * unattributed 5xx (see errors.ts), so it never double-bills regardless.
 */
export class VarstenGemini {
  readonly models: {
    generateContent: (params: any) => Promise<any>;
    generateContentStream: (params: any) => Promise<any>;
  };

  private readonly primary: GoogleGenAI;
  private readonly fallbackClient: GoogleGenAI | null;
  private readonly options: {
    fallback: "auto" | "off";
    fallbackOnReadTimeout: boolean;
    onFallback?: (e: FallbackEvent) => void;
  };
  private readonly breaker: LocalBreaker;
  private readonly emitTelemetry: (event: FallbackEvent) => void;

  constructor(opts: VarstenGeminiOptions = {}) {
    const varstenApiKey = opts.varstenApiKey ?? process.env.VARSTEN_API_KEY;
    const providerApiKey = opts.geminiApiKey ?? process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY;
    const host = varstenHost(opts.baseURL ?? process.env.VARSTEN_BASE_URL ?? DEFAULT_HOST);

    if (!varstenApiKey) {
      throw new Error("varstenApiKey is required (or set VARSTEN_API_KEY).");
    }

    const varstenTotalMs = opts.timeouts?.varstenTotalMs ?? DEFAULT_VARSTEN_TOTAL_MS;
    const providerTotalMs = opts.timeouts?.providerTotalMs;

    // Optimized path: point the SDK at Varsten's host root and bound the attempt.
    this.primary = new GoogleGenAI({
      apiKey: varstenApiKey,
      // X-Varsten-Client lets Varsten record that this project's Gemini traffic runs
      // through the fail-open SDK, powering the dashboard's per-provider coverage
      // status. Only on the optimized client; the direct fallback talks to the provider.
      httpOptions: { baseUrl: host, timeout: varstenTotalMs, headers: { "X-Varsten-Client": SDK_VERSION } },
    });

    // Direct path. Only built when a provider key is present; the provider key
    // never goes to Varsten.
    this.fallbackClient = providerApiKey
      ? new GoogleGenAI({
          apiKey: providerApiKey,
          ...(providerTotalMs ? { httpOptions: { timeout: providerTotalMs } } : {}),
        })
      : null;

    this.options = {
      fallback: opts.fallback ?? "auto",
      fallbackOnReadTimeout: opts.fallbackOnReadTimeout ?? false,
      onFallback: opts.onFallback,
    };
    this.breaker = new LocalBreaker(opts.breakerThreshold ?? 5, opts.breakerCooldownMs ?? 30_000);
    this.emitTelemetry = makeTelemetryEmitter({ baseURL: `${host}/v1`, varstenApiKey });

    this.models = {
      generateContent: (params: any) => this.run(params, false),
      generateContentStream: (params: any) => this.run(params, true),
    };
  }

  private run(params: any, streaming: boolean): Promise<any> {
    const callPrimary = (b: any, idem: string) => {
      const p = withIdempotency(b, idem);
      return streaming
        ? (this.primary.models.generateContentStream(p) as Promise<any>)
        : (this.primary.models.generateContent(p) as Promise<any>);
    };
    const callFallback = this.fallbackClient
      ? (b: any, _idem: string) =>
          streaming
            ? (this.fallbackClient!.models.generateContentStream(b) as Promise<any>)
            : (this.fallbackClient!.models.generateContent(b) as Promise<any>)
      : null;

    return executeWithFallback({
      body: params,
      mode: this.options.fallback,
      streaming,
      provider: PROVIDER,
      errorAdapter: geminiErrorAdapter,
      primaryCreate: callPrimary,
      fallbackCreate: callFallback,
      breaker: this.breaker,
      fallbackOnReadTimeout: this.options.fallbackOnReadTimeout,
      sdkVersion: SDK_VERSION,
      onFallback: this.options.onFallback,
      emitTelemetry: this.emitTelemetry,
    });
  }
}
