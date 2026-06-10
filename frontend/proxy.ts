import { auth0 } from "./lib/auth0";

// Next.js 16 network-boundary interception (replaces middleware.ts). Runs the
// Auth0 session/rolling-cookie handling and serves the /auth/* routes.
export async function proxy(request: Request) {
  return await auth0.middleware(request);
}

// Run only on application pages. Exclude all Next internals (_next/*), the
// favicon and SEO files, and any path with a static-asset extension so the
// Auth0 session handling never intercepts public assets (logos, fonts, css).
export const config = {
  matcher: [
    "/((?!_next|favicon\\.ico|sitemap\\.xml|robots\\.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|avif|ico|css|js|map|txt|xml|woff2?|ttf|otf)$).*)",
  ],
};
