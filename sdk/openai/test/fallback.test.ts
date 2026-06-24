import { describe, expect, it, vi } from "vitest";

import { LocalBreaker } from "../src/breaker.js";
import { classifyError, executeWithFallback, type ExecuteParams } from "../src/fallback.js";
import { VarstenUnavailableError } from "../src/types.js";

// --- error shapes (match what the OpenAI SDK throws + our server's headers) ----

const connError = { name: "APIConnectionError", code: "ECONNREFUSED" };
const dnsError = { name: "APIConnectionError", code: "ENOTFOUND" };
const timeoutError = { name: "APIConnectionTimeoutError" };
const apiErr = (status: number, origin?: string, code?: string) => ({
  status,
  headers: origin ? { "x-varsten-origin": origin } : {},
  error: code || origin ? { code, origin } : undefined,
  code,
});

describe("classifyError", () => {
  const opts = { fallbackOnReadTimeout: false };

  it("falls back on a hard connection failure", () => {
    expect(classifyError(connError, opts).fallback).toBe(true);
    expect(classifyError(dnsError, opts).fallback).toBe(true);
  });

  it("does not fall back on a timeout by default, but does when opted in", () => {
    expect(classifyError(timeoutError, opts).fallback).toBe(false);
    expect(classifyError(timeoutError, { fallbackOnReadTimeout: true }).fallback).toBe(true);
  });

  it("classifies real OpenAI SDK errors that leave .name as 'Error'", () => {
    // Regression: the OpenAI SDK does not set .name, so detection must use the
    // message (and, in production, instanceof). Caught by the e2e smoke test.
    expect(classifyError({ name: "Error", message: "Connection error." }, opts).fallback).toBe(true);
    expect(classifyError({ name: "Error", message: "Request timed out." }, opts).fallback).toBe(false);
    expect(
      classifyError({ name: "Error", message: "Request timed out." }, { fallbackOnReadTimeout: true }).fallback,
    ).toBe(true);
  });

  it("falls back on Varsten-origin failures", () => {
    expect(classifyError(apiErr(503, "varsten", "circuit_open"), opts).fallback).toBe(true);
    expect(classifyError(apiErr(429, "varsten", "rate_limited"), opts).fallback).toBe(true);
    expect(classifyError(apiErr(502, "varsten", "upstream_unreachable"), opts).fallback).toBe(true);
    expect(classifyError(apiErr(502, "varsten", "no_provider_key"), opts).fallback).toBe(true);
  });

  it("never falls back on a relayed provider response", () => {
    expect(classifyError(apiErr(400, "provider"), opts).fallback).toBe(false);
    expect(classifyError(apiErr(401, "provider"), opts).fallback).toBe(false);
    // The critical one: a provider 5xx must NOT trigger a double call.
    expect(classifyError(apiErr(503, "provider"), opts).fallback).toBe(false);
  });

  it("does not fall back on deliberate Varsten non-fallback codes", () => {
    expect(classifyError(apiErr(402, "varsten", "budget_exceeded"), opts).fallback).toBe(false);
    expect(classifyError(apiErr(400, "varsten", "bad_request"), opts).fallback).toBe(false);
    expect(classifyError(apiErr(401, "varsten", "unauthorized"), opts).fallback).toBe(false);
  });

  it("treats a header-less 5xx as Varsten, a header-less 4xx as a client error", () => {
    expect(classifyError(apiErr(500), opts).fallback).toBe(true);
    expect(classifyError(apiErr(400), opts).fallback).toBe(false);
  });

  it("does not fall back on an unknown (non-API, non-connection) error", () => {
    expect(classifyError(new Error("boom"), opts).fallback).toBe(false);
  });

  it("reads origin from the body when the header is absent", () => {
    const e = { status: 503, error: { origin: "provider" } };
    expect(classifyError(e, opts).fallback).toBe(false);
  });
});

// --- executeWithFallback ------------------------------------------------------

function params(over: Partial<ExecuteParams> = {}): ExecuteParams {
  return {
    body: { model: "gpt-4o-mini", messages: [] },
    mode: "auto",
    primaryCreate: vi.fn(async () => ({ ok: "primary" })),
    fallbackCreate: vi.fn(async () => ({ ok: "fallback" })),
    breaker: new LocalBreaker(5, 30_000),
    fallbackOnReadTimeout: false,
    sdkVersion: "test",
    ...over,
  };
}

describe("executeWithFallback", () => {
  it("returns the optimized result and tags it varsten", async () => {
    const res: any = await executeWithFallback(params());
    expect(res.ok).toBe("primary");
    expect(res._varsten.servedBy).toBe("varsten");
  });

  it("falls back to the provider on a connection error and fires onFallback", async () => {
    const onFallback = vi.fn();
    const emitTelemetry = vi.fn();
    const primaryCreate = vi.fn(async () => {
      throw connError;
    });
    const res: any = await executeWithFallback(params({ primaryCreate, onFallback, emitTelemetry }));
    expect(res.ok).toBe("fallback");
    expect(res._varsten.servedBy).toBe("provider-fallback");
    expect(onFallback).toHaveBeenCalledTimes(1);
    expect(emitTelemetry).toHaveBeenCalledTimes(1);
    expect(onFallback.mock.calls[0]![0].reasonCode).toBe("connection_error");
  });

  it("does not fall back (rethrows) on a relayed provider error", async () => {
    const fallbackCreate = vi.fn(async () => ({ ok: "fallback" }));
    const primaryCreate = vi.fn(async () => {
      throw apiErr(503, "provider");
    });
    await expect(executeWithFallback(params({ primaryCreate, fallbackCreate }))).rejects.toBeDefined();
    expect(fallbackCreate).not.toHaveBeenCalled();
  });

  it("falls back on a Varsten-origin 503", async () => {
    const primaryCreate = vi.fn(async () => {
      throw apiErr(503, "varsten", "circuit_open");
    });
    const res: any = await executeWithFallback(params({ primaryCreate }));
    expect(res.ok).toBe("fallback");
  });

  it("does not fall back on a budget cap (402)", async () => {
    const fallbackCreate = vi.fn(async () => ({ ok: "fallback" }));
    const primaryCreate = vi.fn(async () => {
      throw apiErr(402, "varsten", "budget_exceeded");
    });
    await expect(executeWithFallback(params({ primaryCreate, fallbackCreate }))).rejects.toBeDefined();
    expect(fallbackCreate).not.toHaveBeenCalled();
  });

  it("respects fallbackOnReadTimeout", async () => {
    const mk = () =>
      vi.fn(async () => {
        throw timeoutError;
      });
    await expect(executeWithFallback(params({ primaryCreate: mk() }))).rejects.toBeDefined();
    const res: any = await executeWithFallback(params({ primaryCreate: mk(), fallbackOnReadTimeout: true }));
    expect(res.ok).toBe("fallback");
  });

  it("throws VarstenUnavailableError when down with no provider key", async () => {
    const primaryCreate = vi.fn(async () => {
      throw connError;
    });
    await expect(executeWithFallback(params({ primaryCreate, fallbackCreate: null }))).rejects.toBeInstanceOf(
      VarstenUnavailableError,
    );
  });

  it("opens the breaker and stops calling Varsten during a sustained outage", async () => {
    const primaryCreate = vi.fn(async () => {
      throw connError;
    });
    const fallbackCreate = vi.fn(async () => ({ ok: "fallback" }));
    const breaker = new LocalBreaker(1, 30_000);
    const p = { primaryCreate, fallbackCreate, breaker };

    const first: any = await executeWithFallback(params(p));
    expect(first._varsten.reason).toBe("connection_error");
    const second: any = await executeWithFallback(params(p));
    expect(second._varsten.reason).toBe("breaker_open");

    expect(primaryCreate).toHaveBeenCalledTimes(1); // breaker skipped Varsten the 2nd time
    expect(fallbackCreate).toHaveBeenCalledTimes(2);
  });

  it("mode=off goes straight through with no fallback", async () => {
    const fallbackCreate = vi.fn(async () => ({ ok: "fallback" }));
    const primaryCreate = vi.fn(async () => {
      throw connError;
    });
    await expect(executeWithFallback(params({ mode: "off", primaryCreate, fallbackCreate }))).rejects.toBeDefined();
    expect(fallbackCreate).not.toHaveBeenCalled();
  });
});
