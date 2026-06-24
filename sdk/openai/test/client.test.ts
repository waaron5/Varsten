import { describe, expect, it, vi } from "vitest";

import { VarstenOpenAI } from "../src/client.js";

describe("VarstenOpenAI construction", () => {
  it("requires a Varsten key", () => {
    vi.stubEnv("VARSTEN_API_KEY", "");
    expect(() => new VarstenOpenAI({})).toThrow(/varstenApiKey is required/);
    vi.unstubAllEnvs();
  });

  it("builds with both keys and exposes the OpenAI-shaped surface", () => {
    const client = new VarstenOpenAI({ varstenApiKey: "vk_test", openaiApiKey: "sk-test" });
    expect(typeof client.chat.completions.create).toBe("function");
  });

  it("does not require a provider key to construct (fallback simply disabled)", () => {
    const client = new VarstenOpenAI({ varstenApiKey: "vk_test" });
    expect(typeof client.chat.completions.create).toBe("function");
  });
});
