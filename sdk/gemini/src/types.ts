// Shared types live in @varsten/core. This package re-exports them and adds the
// two Gemini-specific bits: the package version label and the provider-key option.
import type { VarstenClientOptions } from "@varsten/core";

export * from "@varsten/core";

/** Package label sent on telemetry markers so the dashboard can attribute a
 * fallback to the Gemini wrapper. */
export const SDK_VERSION = "varsten-gemini/0.1.0";

/** The upstream provider this wrapper targets; stamped onto telemetry. */
export const PROVIDER = "gemini";

export interface VarstenGeminiOptions extends VarstenClientOptions {
  /** The provider key. Stays local; used only on direct fallback. Falls back to
   * process.env.GEMINI_API_KEY or process.env.GOOGLE_API_KEY. Never sent to Varsten. */
  geminiApiKey?: string;
}
