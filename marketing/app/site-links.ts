// Overridable for local dev so the marketing CTAs can point at a local dashboard
// (http://localhost:3000) instead of production. Unset in prod, so the default
// here is what actually ships.
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "https://app.varsten.ai";
export const CONTACT_EMAIL = "mail@varsten.ai";
export const DPA_REQUEST_HREF = `mailto:${CONTACT_EMAIL}?subject=DPA%20request`;
// Self-serve entries preserve buyer intent through auth and account provisioning:
// trial starts Performance access immediately, observe creates/keeps Free mode.
export const START_TRIAL_HREF = `${APP_URL}/start?intent=trial`;
export const START_OBSERVE_HREF = `${APP_URL}/start?intent=observe`;
export const START_FREE_HREF = START_TRIAL_HREF;
