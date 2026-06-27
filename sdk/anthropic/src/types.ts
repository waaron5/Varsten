// Shared types live in @varsten/core. This package re-exports them and adds the
// two Anthropic-specific bits: the package version label and the provider-key option.
import type { VarstenClientOptions } from "@varsten/core";

export * from "@varsten/core";

/** Package label sent on telemetry markers so the dashboard can attribute a
 * fallback to the Anthropic wrapper. */
export const SDK_VERSION = "varsten-anthropic/0.1.0";

/** The upstream provider this wrapper targets; stamped onto telemetry. */
export const PROVIDER = "anthropic";

export interface VarstenAnthropicOptions extends VarstenClientOptions {
  /** The provider key. Stays local; used only on direct fallback. Falls back to
   * process.env.ANTHROPIC_API_KEY. Never sent to Varsten. */
  anthropicApiKey?: string;
}
