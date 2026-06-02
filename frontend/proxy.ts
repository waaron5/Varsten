import { auth0 } from "./lib/auth0";

// Next.js 16 network-boundary interception (replaces middleware.ts). Runs the
// Auth0 session/rolling-cookie handling and serves the /auth/* routes.
export async function proxy(request: Request) {
  return await auth0.middleware(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
};
