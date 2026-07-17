/**
 * Minimal example: optimize through Varsten, fall back to Anthropic directly if
 * Varsten is unavailable.
 *
 *   VARSTEN_API_KEY=vk_... ANTHROPIC_API_KEY=sk-ant-... npx tsx examples/basic.ts
 *
 * To see fallback in action, point the SDK at a dead Varsten and watch it serve
 * directly from the provider:
 *
 *   VARSTEN_BASE_URL=http://127.0.0.1:1   (nothing listening)
 */
import { VarstenAnthropic } from "../src/index.js";

const client = new VarstenAnthropic({
  // Reads VARSTEN_API_KEY / ANTHROPIC_API_KEY / VARSTEN_BASE_URL from the environment.
  onFallback: (event) => {
    console.warn(`[varsten] fell back to provider: ${event.reasonCode} (${event.latencyMs}ms)`);
  },
});

const res = await client.messages.create({
  model: "claude-haiku-4-5-20251001",
  max_tokens: 64,
  messages: [{ role: "user", content: "Say hello in five words." }],
});

const meta = (res as { _varsten?: { servedBy: string } })._varsten;
console.log("served by:", meta?.servedBy);
console.log("response:", res.content?.[0]?.type === "text" ? res.content[0].text : res.content);
