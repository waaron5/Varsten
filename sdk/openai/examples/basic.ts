/**
 * Minimal example: optimize through Varsten, fall back to the provider directly
 * if Varsten is unavailable.
 *
 *   VARSTEN_API_KEY=vk_... OPENAI_API_KEY=sk-... npx tsx examples/basic.ts
 *
 * To see fallback in action, point the SDK at a dead Varsten and watch it serve
 * directly from the provider:
 *
 *   VARSTEN_BASE_URL=http://127.0.0.1:1   (nothing listening)
 */
import { VarstenOpenAI } from "../src/index.js";

const client = new VarstenOpenAI({
  // Reads VARSTEN_API_KEY / OPENAI_API_KEY / VARSTEN_BASE_URL from the environment.
  onFallback: (event) => {
    console.warn(`[varsten] fell back to provider: ${event.reasonCode} (${event.latencyMs}ms)`);
  },
});

const res = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "Say hello in five words." }],
});

const meta = (res as { _varsten?: { servedBy: string } })._varsten;
console.log("served by:", meta?.servedBy);
console.log("response:", res.choices[0]?.message?.content);
