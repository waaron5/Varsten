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
  "free audit started",
  "sales intent started",
  "contact intent started",
  "early access intent started",
  "enterprise call intent started",
  "contact request submitted",
  "early access requested",
  "enterprise call requested",
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isBlockedProperty(key: string): boolean {
  const normalizedKey = key.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  return blockedPropertyFragments.some((fragment) => normalizedKey.includes(fragment));
}

function safeAnalyticsValue(value: unknown): AnalyticsProperties[string] | undefined {
  const allowedTypes = ["number", "boolean"];
  if (typeof value === "string") return value.slice(0, 500);
  if (allowedTypes.includes(typeof value) || value === null) return value as AnalyticsProperties[string];
  return undefined;
}

export function safeAnalyticsProperties(properties: unknown): AnalyticsProperties {
  if (!isRecord(properties)) return {};

  return Object.entries(properties).reduce<AnalyticsProperties>((safe, [key, value]) => {
    if (isBlockedProperty(key)) return safe;

    const safeValue = safeAnalyticsValue(value);
    if (safeValue !== undefined) safe[key] = safeValue;

    return safe;
  }, {});
}
