import { ApiError } from "@google/genai";
import { describe, expect, it, vi } from "vitest";

import { classifyError } from "@varsten/core";

import { VarstenGemini } from "../src/client.js";
import { geminiErrorAdapter } from "../src/errors.js";

describe("VarstenGemini construction", () => {
  it("requires a Varsten key", () => {
    vi.stubEnv("VARSTEN_API_KEY", "");
    expect(() => new VarstenGemini({})).toThrow(/varstenApiKey is required/);
    vi.unstubAllEnvs();
  });

  it("builds with both keys and exposes the Gen AI-shaped surface", () => {
    const client = new VarstenGemini({ varstenApiKey: "vk_test", geminiApiKey: "AIza-test" });
    expect(typeof client.models.generateContent).toBe("function");
    expect(typeof client.models.generateContentStream).toBe("function");
  });

  it("does not require a provider key to construct (fallback simply disabled)", () => {
    const client = new VarstenGemini({ varstenApiKey: "vk_test" });
    expect(typeof client.models.generateContent).toBe("function");
  });
});

// Varsten errors reach the Gen AI SDK as an ApiError whose `message` is the
// stringified response body. These mirror exactly what the proxy emits.
const varstenError = (status: number, code: string) =>
  new ApiError({
    message: JSON.stringify({ error: { message: "x", type: `varsten_${code}`, code, origin: "varsten" } }),
    status,
  });

// A relayed provider error has no `origin` in its body and (critically) no
// readable header on the Gen AI ApiError.
const relayedProviderError = (status: number) =>
  new ApiError({
    message: JSON.stringify({ error: { code: status, message: "provider failed", status: "INTERNAL" } }),
    status,
  });

describe("geminiErrorAdapter", () => {
  const opts = { fallbackOnReadTimeout: false };

  it("falls back on positively Varsten-attributed errors (body origin=varsten)", () => {
    expect(classifyError(varstenError(503, "circuit_open"), opts, geminiErrorAdapter).fallback).toBe(true);
    expect(classifyError(varstenError(429, "rate_limited"), opts, geminiErrorAdapter).fallback).toBe(true);
    expect(classifyError(varstenError(502, "upstream_unreachable"), opts, geminiErrorAdapter).fallback).toBe(true);
    expect(classifyError(varstenError(502, "no_provider_key"), opts, geminiErrorAdapter).fallback).toBe(true);
  });

  it("does NOT fall back on a relayed provider 5xx (no double-bill, header unreadable)", () => {
    // This is the case that would double-bill under the default header-less-5xx
    // rule; the Gemini adapter opts out of it.
    expect(classifyError(relayedProviderError(503), opts, geminiErrorAdapter).fallback).toBe(false);
    expect(classifyError(relayedProviderError(500), opts, geminiErrorAdapter).fallback).toBe(false);
  });

  it("does not fall back on deliberate Varsten non-fallback codes", () => {
    expect(classifyError(varstenError(402, "budget_exceeded"), opts, geminiErrorAdapter).fallback).toBe(false);
  });

  it("falls back on a fetch connection failure (TypeError with errno cause)", () => {
    const err = Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNREFUSED" } });
    expect(classifyError(err, opts, geminiErrorAdapter).fallback).toBe(true);
  });

  it("treats an AbortError as a timeout (no fallback unless opted in)", () => {
    const abort = Object.assign(new Error("This operation was aborted"), { name: "AbortError" });
    expect(classifyError(abort, opts, geminiErrorAdapter).fallback).toBe(false);
    expect(classifyError(abort, { fallbackOnReadTimeout: true }, geminiErrorAdapter).fallback).toBe(true);
  });
});
