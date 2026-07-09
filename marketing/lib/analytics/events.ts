export const ANALYTICS_EVENTS = [
  "marketing page viewed",
  "docs page viewed",
  "docs code copied",
  "cta clicked",
  "pricing plan selected",
  "lead form started",
  "lead form submitted",
  "lead form failed",
  "trial intent started",
  "observe intent started",
  "sales intent started",
  "resource nav opened",
] as const;

export type AnalyticsEventName = (typeof ANALYTICS_EVENTS)[number];

export type AnalyticsProperties = Record<string, string | number | boolean | null | undefined>;

const eventSet = new Set<string>(ANALYTICS_EVENTS);

export function isAnalyticsEventName(event: string): event is AnalyticsEventName {
  return eventSet.has(event);
}

const blockedPropertyFragments = [
  "api_key",
  "apikey",
  "body",
  "completion",
  "email",
  "form",
  "key",
  "message",
  "name",
  "prompt",
  "secret",
  "token",
];

export function safeAnalyticsProperties(properties: unknown): AnalyticsProperties {
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return {};

  return Object.entries(properties as Record<string, unknown>).reduce<AnalyticsProperties>((safe, [key, value]) => {
    const normalizedKey = key.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    if (blockedPropertyFragments.some((fragment) => normalizedKey.includes(fragment))) return safe;

    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      value === null
    ) {
      safe[key] = typeof value === "string" ? value.slice(0, 500) : value;
    }

    return safe;
  }, {});
}
