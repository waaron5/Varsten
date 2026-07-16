import { StartRedirect } from "@/components/StartRedirect";
import { auth0 } from "@/lib/auth0";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Self-serve entry point linked from the marketing site's "Start free" CTA.
// Routes a signed-in user into onboarding (if unfinished) or the dashboard.
export default async function StartPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  // Honor the same e2e auth bypass the root layout uses, so mocked Playwright
  // runs can exercise the funnel without a real Auth0 tenant.
  const bypass = e2eAuthBypassEnabled((await cookies()).get("varsten_e2e_auth")?.value);
  const session = bypass ? null : await auth0.getSession();
  if (!bypass && !session) {
    redirect(`/auth/login?screen_hint=signup&returnTo=${encodeURIComponent(startReturnTo(params))}`);
  }
  return <StartRedirect />;
}

function e2eAuthBypassEnabled(cookieValue: string | undefined): boolean {
  if (process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1") return true;
  return process.env.NODE_ENV === "development" && cookieValue === "1";
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
