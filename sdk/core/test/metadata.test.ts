import { describe, expect, it } from "vitest";

import { VarstenTrace, metadataHeaderValue } from "../src/metadata.js";

describe("metadataHeaderValue", () => {
  it("maps camelCase fields to the proxy's snake_case keys", () => {
    const value = metadataHeaderValue({
      traceId: "trace-1",
      feature: "support_agent",
      customerId: "cust_9",
      taskType: "classification.intent",
      riskLevel: "low",
    });
    expect(value).not.toBeNull();
    expect(JSON.parse(value!)).toEqual({
      trace_id: "trace-1",
      feature: "support_agent",
      customer_id: "cust_9",
      task_type: "classification.intent",
      risk_level: "low",
    });
  });

  it("passes extra labels through as-is", () => {
    const value = metadataHeaderValue({ feature: "faq", extra: { task_confidence: 0.95, tier: "pro" } });
    expect(JSON.parse(value!)).toEqual({ feature: "faq", task_confidence: 0.95, tier: "pro" });
  });

  it("drops empty values and returns null when nothing remains", () => {
    expect(metadataHeaderValue(undefined)).toBeNull();
    expect(metadataHeaderValue({})).toBeNull();
    expect(metadataHeaderValue({ feature: "", traceId: undefined })).toBeNull();
  });
});

describe("VarstenTrace", () => {
  it("stamps every call's metadata with one trace id", () => {
    const trace = new VarstenTrace();
    const a = trace.metadata({ taskType: "research.step" });
    const b = trace.metadata();
    expect(a.traceId).toBe(trace.traceId);
    expect(b.traceId).toBe(trace.traceId);
    expect(a.taskType).toBe("research.step");
    expect(trace.traceId).toMatch(/^trace-/);
  });

  it("accepts a caller-provided id and never overrides it per call", () => {
    const trace = new VarstenTrace("run-42");
    expect(trace.metadata({ traceId: "ignored" }).traceId).toBe("run-42");
  });
});
