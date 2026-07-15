import { StartRedirect } from "@/components/StartRedirect";
import { auth0 } from "@/lib/auth0";
import { redirect } from "next/navigation";

// Self-serve entry point linked from the marketing site's "Start free" CTA.
// Routes a signed-in user into onboarding (if unfinished) or the dashboard.
export default async function StartPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await auth0.getSession();
  const params = (await searchParams) ?? {};
  if (!session) {
    redirect(`/auth/login?screen_hint=signup&returnTo=${encodeURIComponent(startReturnTo(params))}`);
  }
  return <StartRedirect />;
}

function startReturnTo(params: Record<string, string | string[] | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, item);
    } else if (value) {
      query.set(key, value);
    }
  }
  const serialized = query.toString();
  return serialized ? `/start?${serialized}` : "/start";
}
