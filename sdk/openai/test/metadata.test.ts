import { describe, expect, it } from "vitest";

import { VarstenOpenAI } from "../src/client.js";
import { VARSTEN_METADATA_HEADER, VarstenTrace } from "../src/types.js";

const connError = { name: "APIConnectionError", code: "ECONNREFUSED" };

function stubClients(client: VarstenOpenAI) {
  const primaryCalls: Array<{ body: any; options: any }> = [];
  const fallbackCalls: Array<{ body: any; options: any }> = [];
  (client as any).primary = {
    chat: {
      completions: {
        create: (body: any, options: any) => {
          primaryCalls.push({ body, options });
          return Promise.resolve({ id: "from-varsten" });
        },
      },
    },
  };
  (client as any).fallbackClient = {
    chat: {
      completions: {
        create: (body: any, options: any) => {
          fallbackCalls.push({ body, options });
          return Promise.resolve({ id: "from-provider" });
        },
      },
    },
  };
  return { primaryCalls, fallbackCalls };
}

function onlyCall<T>(calls: T[]): T {
  const call = calls[0];
  if (!call) {
    throw new Error("expected exactly one SDK call");
  }
  return call;
}

describe("workflow metadata", () => {
  it("rides the optimized attempt as X-Varsten-Metadata", async () => {
    const client = new VarstenOpenAI({ varstenApiKey: "vk_test", openaiApiKey: "sk-test" });
    const { primaryCalls } = stubClients(client);
    const trace = new VarstenTrace("run-7");

    await client.chat.completions.create(
      { model: "gpt-4o-mini", messages: [] },
      { varsten: trace.metadata({ feature: "support_agent", taskType: "classification.intent" }) },
    );

    expect(primaryCalls).toHaveLength(1);
    const call = onlyCall(primaryCalls);
    const header = call.options.headers[VARSTEN_METADATA_HEADER];
    expect(JSON.parse(header)).toEqual({
      trace_id: "run-7",
      feature: "support_agent",
      task_type: "classification.intent",
    });
    // The idempotency key still rides alongside the metadata.
    expect(call.options.idempotencyKey).toMatch(/^varsten-/);
  });

  it("never reaches the direct provider fallback", async () => {
    const client = new VarstenOpenAI({ varstenApiKey: "vk_test", openaiApiKey: "sk-test" });
    const { fallbackCalls } = stubClients(client);
    (client as any).primary.chat.completions.create = () => Promise.reject(connError);

    const res = await client.chat.completions.create(
      { model: "gpt-4o-mini", messages: [] },
      { varsten: { feature: "support_agent", customerId: "cust_1" } },
    );

    expect(res.id).toBe("from-provider");
    expect(fallbackCalls).toHaveLength(1);
    const call = onlyCall(fallbackCalls);
    expect(call.options.headers).toBeUndefined();
    expect(JSON.stringify(call.options)).not.toContain("support_agent");
  });

  it("sends no header at all when no metadata is given", async () => {
    const client = new VarstenOpenAI({ varstenApiKey: "vk_test", openaiApiKey: "sk-test" });
    const { primaryCalls } = stubClients(client);

    await client.chat.completions.create({ model: "gpt-4o-mini", messages: [] });

    expect(onlyCall(primaryCalls).options.headers).toBeUndefined();
  });
});
