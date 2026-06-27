import Anthropic from "@anthropic-ai/sdk";
import { describe, expect, it, vi } from "vitest";

import { classifyError } from "@varsten/core";

import { VarstenAnthropic } from "../src/client.js";
import { anthropicErrorAdapter } from "../src/errors.js";

describe("VarstenAnthropic construction", () => {
  it("requires a Varsten key", () => {
    vi.stubEnv("VARSTEN_API_KEY", "");
    expect(() => new VarstenAnthropic({})).toThrow(/varstenApiKey is required/);
    vi.unstubAllEnvs();
  });

  it("builds with both keys and exposes the Anthropic-shaped surface", () => {
    const client = new VarstenAnthropic({ varstenApiKey: "vk_test", anthropicApiKey: "sk-ant-test" });
    expect(typeof client.messages.create).toBe("function");
  });

  it("does not require a provider key to construct (fallback simply disabled)", () => {
    const client = new VarstenAnthropic({ varstenApiKey: "vk_test" });
    expect(typeof client.messages.create).toBe("function");
  });
});

describe("anthropicErrorAdapter", () => {
  const opts = { fallbackOnReadTimeout: false };

  it("falls back on the Anthropic SDK's own connection error (instanceof)", () => {
    const err = new Anthropic.APIConnectionError({ message: "Connection error." });
    expect(classifyError(err, opts, anthropicErrorAdapter).fallback).toBe(true);
  });

  it("does not fall back on a relayed provider error (origin=provider)", () => {
    const err = {
      status: 503,
      headers: { "x-varsten-origin": "provider" },
      error: { origin: "provider" },
    };
    expect(classifyError(err, opts, anthropicErrorAdapter).fallback).toBe(false);
  });

  it("falls back on a Varsten-origin circuit-open (origin=varsten)", () => {
    const err = {
      status: 503,
      headers: { "x-varsten-origin": "varsten" },
      error: { origin: "varsten", code: "circuit_open" },
      code: "circuit_open",
    };
    expect(classifyError(err, opts, anthropicErrorAdapter).fallback).toBe(true);
  });
});
