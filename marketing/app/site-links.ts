// Overridable for local dev so the marketing CTAs can point at a local dashboard
// (http://localhost:3000) instead of production. Unset in prod, so the default
// here is what actually ships.
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "https://app.varsten.ai";
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://varsten.ai").replace(/\/+$/, "");
export const CONTACT_EMAIL = "mail@varsten.ai";
export const DPA_REQUEST_HREF = `mailto:${CONTACT_EMAIL}?subject=DPA%20request`;
export const AI_COST_REPORT_HREF = "https://aaronwoodcs.substack.com/subscribe";
// Self-serve entries preserve buyer intent through auth and account provisioning:
// trial starts Optimize access immediately, observe creates/keeps Free mode.
export const START_TRIAL_HREF = `${APP_URL}/start?intent=trial`;
export const START_OBSERVE_HREF = `${APP_URL}/start?intent=observe`;
export const START_FREE_HREF = START_TRIAL_HREF;

export function siteUrl(path = "/") {
  return new URL(path, `${SITE_URL}/`).toString();
}
