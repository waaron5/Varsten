// Overridable for local dev so the marketing CTAs can point at a local dashboard
// (http://localhost:3000) instead of production. Unset in prod, so the default
// here is what actually ships.
const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "https://app.varsten.ai";
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://varsten.ai").replace(/\/+$/, "");
export const CONTACT_EMAIL = "contact@varsten.ai";
export const CONTACT_HREF = "/contact";
export const EARLY_ACCESS_HREF = "/early-access";
export const ENTERPRISE_FORM_HREF = "/enterprise#enterprise-form";
export const DPA_REQUEST_HREF = `mailto:${CONTACT_EMAIL}?subject=DPA%20request`;
export const AI_COST_REPORT_HREF = "https://aaronwoodcs.substack.com/subscribe";
// Base remains available as a product entry point. Pro access is
// founder-reviewed during public preview, so public CTAs use EARLY_ACCESS_HREF.
export const START_OBSERVE_HREF = `${APP_URL}/start?intent=observe`;
export const SIGN_IN_HREF = `${APP_URL}/auth/login?returnTo=${encodeURIComponent("/dashboard")}`;

export function siteUrl(path = "/") {
  return new URL(path, `${SITE_URL}/`).toString();
}
