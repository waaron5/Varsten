import { StartRedirect } from "@/components/StartRedirect";

// Self-serve entry point linked from the marketing site's "Start free" CTA.
// Routes a signed-in user into onboarding (if unfinished) or the dashboard.
export default function StartPage() {
  return <StartRedirect />;
}
