import Anthropic from "@anthropic-ai/sdk";

import { makeStainlessAdapter, type ProviderErrorAdapter } from "@varsten/core";

/** Anthropic's SDK is stainless-generated like OpenAI's: it ships
 * `APIConnectionError` / `APIConnectionTimeoutError` and exposes `.status` and
 * `.headers` on API errors, so the shared stainless adapter applies unchanged.
 * The X-Varsten-Origin header is read off the error's response headers exactly as
 * for OpenAI. */
export const anthropicErrorAdapter: ProviderErrorAdapter = makeStainlessAdapter({
  APIConnectionError: Anthropic.APIConnectionError,
  APIConnectionTimeoutError: Anthropic.APIConnectionTimeoutError,
});
