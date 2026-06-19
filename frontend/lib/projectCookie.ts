// The active project id is persisted in a cookie (not localStorage) so the
// server can read it during the first render and resolve the same active project
// the client would pick. Shared by the client session layer and the server
// bootstrap; this module is intentionally free of any client- or server-only
// runtime so both can import it.

export const ACTIVE_PROJECT_COOKIE = "varsten_active_project";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

export function readActiveProjectCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${ACTIVE_PROJECT_COOKIE}=([^;]+)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function writeActiveProjectCookie(id: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${ACTIVE_PROJECT_COOKIE}=${encodeURIComponent(id)}; path=/; max-age=${ONE_YEAR_SECONDS}; samesite=lax`;
}
