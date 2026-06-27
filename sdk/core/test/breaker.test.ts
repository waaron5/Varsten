import { describe, expect, it } from "vitest";

import { LocalBreaker } from "../src/breaker.js";

describe("LocalBreaker", () => {
  it("allows by default", () => {
    expect(new LocalBreaker().allow()).toBe(true);
  });

  it("opens after the threshold of consecutive failures", () => {
    let t = 1000;
    const b = new LocalBreaker(2, 100, () => t);
    expect(b.allow()).toBe(true);
    b.recordVarstenFailure();
    expect(b.allow()).toBe(true);
    b.recordVarstenFailure(); // hits threshold -> open
    expect(b.allow()).toBe(false);
  });

  it("half-opens after cooldown and reopens on a probe failure", () => {
    let t = 1000;
    const b = new LocalBreaker(2, 100, () => t);
    b.recordVarstenFailure();
    b.recordVarstenFailure();
    expect(b.allow()).toBe(false);

    t = 1000 + 200; // past the (jittered <=120ms) cooldown
    expect(b.allow()).toBe(true); // single probe permitted

    b.recordVarstenFailure(); // probe failed -> reopen
    expect(b.allow()).toBe(false);
  });

  it("closes on success", () => {
    let t = 1000;
    const b = new LocalBreaker(1, 100, () => t);
    b.recordVarstenFailure();
    expect(b.allow()).toBe(false);
    b.recordSuccess();
    expect(b.allow()).toBe(true);
  });

  it("only counts Varsten failures (a success between failures resets the count)", () => {
    const b = new LocalBreaker(3, 100);
    b.recordVarstenFailure();
    b.recordVarstenFailure();
    b.recordSuccess();
    b.recordVarstenFailure();
    expect(b.allow()).toBe(true); // never reached 3 in a row
  });
});
