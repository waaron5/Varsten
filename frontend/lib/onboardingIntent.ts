export type OnboardingIntent = "trial" | "observe";

const INTENTS = new Set<OnboardingIntent>(["trial", "observe"]);

function normalizeOnboardingIntent(value: string | null | undefined): OnboardingIntent | undefined {
  return value && INTENTS.has(value as OnboardingIntent) ? (value as OnboardingIntent) : undefined;
}

export function currentOnboardingIntent(): OnboardingIntent | undefined {
  if (typeof window === "undefined") return undefined;
  return normalizeOnboardingIntent(new URLSearchParams(window.location.search).get("intent"));
}
