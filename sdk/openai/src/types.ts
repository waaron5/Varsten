// Shared types live in @varsten/core. This package re-exports them and adds the
// two OpenAI-specific bits: the package version label and the provider-key option.
import type { VarstenClientOptions } from "@varsten/core";

export * from "@varsten/core";

/** Package label sent on telemetry markers so the dashboard can attribute a
 * fallback to the OpenAI wrapper. */
export const SDK_VERSION = "varsten-openai/0.1.0";

export interface VarstenOptions extends VarstenClientOptions {
  /** The provider key. Stays local; used only on direct fallback. Falls back to
   * process.env.OPENAI_API_KEY. Never sent to Varsten. */
  openaiApiKey?: string;
}
