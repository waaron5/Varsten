import { ANALYTICS_EVENTS, type AnalyticsEventName, type AnalyticsProperties, safeAnalyticsProperties } from "./events";

const posthogHost =
  (process.env.POSTHOG_HOST || process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com").replace(/\/+$/, "");

function posthogKey() {
  return process.env.POSTHOG_KEY || process.env.NEXT_PUBLIC_POSTHOG_KEY || "";
}

function analyticsDisabled() {
  return process.env.POSTHOG_DISABLED === "true" || process.env.NEXT_PUBLIC_POSTHOG_DISABLED === "true";
}

function knownEvent(event: string): event is AnalyticsEventName {
  return (ANALYTICS_EVENTS as readonly string[]).includes(event);
}

export async function captureServerEvent({
  event,
  distinctId,
  properties = {},
}: {
  event: AnalyticsEventName;
  distinctId: string;
  properties?: AnalyticsProperties;
}) {
  if (analyticsDisabled()) return { captured: false, reason: "disabled" as const };
  if (!knownEvent(event)) return { captured: false, reason: "unknown-event" as const };

  const apiKey = posthogKey();
  if (!apiKey) {
    if (process.env.NODE_ENV !== "production") {
      console.log("[analytics disabled] missing PostHog key:", event, properties);
    }
    return { captured: false, reason: "missing-key" as const };
  }

  const response = await fetch(`${posthogHost}/capture/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key: apiKey,
      event,
      distinct_id: distinctId,
      properties: {
        ...safeAnalyticsProperties(properties),
        $lib: "varsten-marketing",
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`PostHog capture failed with ${response.status}`);
  }

  return { captured: true, reason: "ok" as const };
}
