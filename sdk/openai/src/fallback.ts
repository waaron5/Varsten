// The fallback decision and the execution engine live in @varsten/core. This file
// binds them to OpenAI's error shape: OpenAI throws APIConnectionError /
// APIConnectionTimeoutError, so the stainless adapter uses instanceof on those as
// the authoritative transport signal. The public function signatures are unchanged
// so existing imports and tests keep working.
import OpenAI from "openai";

import {
  annotate,
  classifyError as coreClassifyError,
  executeWithFallback as coreExecuteWithFallback,
  makeStainlessAdapter,
  type ExecuteParams,
  type FallbackDecision,
  type ProviderErrorAdapter,
} from "@varsten/core";

/** OpenAI error adapter: generic fetch/stainless signal reading plus instanceof on
 * the OpenAI SDK's own connection/timeout error classes. */
export const openaiErrorAdapter: ProviderErrorAdapter = makeStainlessAdapter({
  APIConnectionError: OpenAI.APIConnectionError,
  APIConnectionTimeoutError: OpenAI.APIConnectionTimeoutError,
});

export function classifyError(err: any, opts: { fallbackOnReadTimeout: boolean }): FallbackDecision {
  return coreClassifyError(err, opts, openaiErrorAdapter);
}

export function executeWithFallback(params: ExecuteParams): Promise<any> {
  // Default the provider tag and error adapter; an explicit caller value wins.
  return coreExecuteWithFallback({ provider: "openai", errorAdapter: openaiErrorAdapter, ...params });
}

export { annotate };
export type { CreateFn, ExecuteParams } from "@varsten/core";
