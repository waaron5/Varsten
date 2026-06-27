/** Normalize a Varsten base URL to its host root.
 *
 * The frozen `VARSTEN_BASE_URL` default is OpenAI-shaped (`https://api.varsten.ai/v1`)
 * because the OpenAI SDK is given the full `/v1` base. The Anthropic and Gemini
 * SDKs append their own version path (`/v1/messages`, `/v1beta/models/...`), so
 * those wrappers need the host root. This strips a trailing `/v1` and any trailing
 * slashes so one env var works for every wrapper.
 */
export function varstenHost(baseURL: string): string {
  return baseURL.replace(/\/+$/, "").replace(/\/v1$/, "");
}
