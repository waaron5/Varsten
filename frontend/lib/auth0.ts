import { Auth0Client } from "@auth0/nextjs-auth0/server";

// Reads AUTH0_DOMAIN / AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET / AUTH0_SECRET /
// APP_BASE_URL from the environment. The SDK auto-mounts /auth/login,
// /auth/logout, /auth/callback, and /auth/profile via the proxy.
//
// audience is required so Auth0 issues a JWT access token for our API (rather
// than an opaque /userinfo token) that the FastAPI backend can validate.
export const auth0 = new Auth0Client({
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE,
    scope: "openid profile email offline_access",
  },
});
