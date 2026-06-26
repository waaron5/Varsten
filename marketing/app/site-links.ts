export const APP_URL = "https://app.varsten.ai";
export const CONTACT_EMAIL = "mail@varsten.ai";
export const DPA_REQUEST_HREF = `mailto:${CONTACT_EMAIL}?subject=DPA%20request`;
// Self-serve entry: "Start free" sends people into the app's onboarding funnel,
// not a lead-capture modal. The app's /start route routes them to onboarding or
// the dashboard based on their state.
export const START_FREE_HREF = `${APP_URL}/start`;
