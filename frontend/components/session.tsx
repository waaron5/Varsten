"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useUser } from "@auth0/nextjs-auth0";
import { api } from "@/lib/api";
import { readActiveProjectCookie, writeActiveProjectCookie } from "@/lib/projectCookie";
import type { Project, UserProfile } from "@/lib/types";
const AUTH_LOADING_TIMEOUT_MS = 12000;
const ACCESS_TOKEN_TIMEOUT_MS = 12000;
const BOOTSTRAP_TIMEOUT_MS = 20000;

type Status = "loading" | "anonymous" | "ready" | "error";

interface SessionValue {
  status: Status;
  profile: UserProfile | null;
  projects: Project[];
  activeProjectId: string | null;
  setActiveProjectId: (id: string) => void;
  refreshProjects: () => Promise<void>;
  getToken: () => Promise<string>;
  error: string | null;
  loadingLabel: string | null;
}

const SessionContext = createContext<SessionValue | null>(null);

type PickActiveProject = (list: Project[]) => void;
type AuthUser = { email?: string | null; name?: string | null };

const E2E_AUTH_USER: AuthUser = {
  email: "maya@enterprise.example",
  name: "Maya Chen",
};

function e2eAuthUser(): AuthUser | null {
  // Test seam for Playwright. CI gets the explicit build-time flag from
  // playwright.config.ts; local dev can reuse an already-running Next server via
  // a development-only cookie. Production builds do not set either path.
  const envEnabled = process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1";
  const devCookieEnabled =
    process.env.NODE_ENV === "development" &&
    typeof document !== "undefined" &&
    document.cookie.split(";").some((cookie) => cookie.trim() === "varsten_e2e_auth=1");
  if (!envEnabled && !devCookieEnabled) return null;
  return E2E_AUTH_USER;
}

function authErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const error = "error" in body ? body.error : null;
  if (error && typeof error === "object" && "message" in error) {
    return String(error.message);
  }
  if (typeof error === "string") return error;
  if ("error_description" in body) return String(body.error_description);
  return fallback;
}

// Access tokens are cached in module scope and reused until they are about to
// expire, so the many resource hooks that mount on a single page (the Dashboard
// alone mounts ~8) share one token instead of each hitting /auth/access-token.
// A shared in-flight promise collapses a concurrent burst into a single fetch.
// Module state resets on logout/login because both are full-page navigations.
const TOKEN_REFRESH_WINDOW_MS = 60_000;
// Used when a token's expiry cannot be read (e.g. an opaque, non-JWT token):
// cache briefly so the concurrent-mount burst still dedups, but refresh often
// enough that a stale token self-heals on the next load.
const TOKEN_FALLBACK_TTL_MS = 5 * 60_000;

let cachedToken: { token: string; expiresAtMs: number } | null = null;
let inFlightToken: Promise<string> | null = null;

// Best-effort read of the JWT `exp` claim (seconds since epoch) without a
// dependency. Returns null for opaque tokens or malformed payloads.
function jwtExpiryMs(token: string): number | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = JSON.parse(globalThis.atob(base64)) as { exp?: number };
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

// Drops the cached token so the next request fetches a fresh one. Exposed for
// callers that learn the token is bad (e.g. an API 401) before its cached expiry.
export function invalidateAccessToken(): void {
  cachedToken = null;
  inFlightToken = null;
}

async function fetchAccessToken(): Promise<string> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, ACCESS_TOKEN_TIMEOUT_MS);

  try {
    const response = await fetch("/auth/access-token", {
      cache: "no-store",
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = "Could not load your authentication token.";
      try {
        message = authErrorMessage(await response.json(), message);
      } catch {
        // Keep the generic message for non-JSON failures.
      }
      throw new Error(message);
    }

    const body = (await response.json()) as { token?: string };
    if (!body.token) throw new Error("Authentication succeeded but no API access token was returned.");
    return body.token;
  } catch (error) {
    if (timedOut || (error instanceof Error && error.name === "AbortError")) {
      throw new Error("Authentication timed out while requesting an API token. Try signing out and signing in again.");
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
  }
}

async function getAccessTokenWithTimeout(): Promise<string> {
  if (cachedToken && cachedToken.expiresAtMs - TOKEN_REFRESH_WINDOW_MS > Date.now()) {
    return cachedToken.token;
  }
  if (inFlightToken) return inFlightToken;

  inFlightToken = (async () => {
    try {
      const token = await fetchAccessToken();
      const expiresAtMs = jwtExpiryMs(token) ?? Date.now() + TOKEN_FALLBACK_TTL_MS;
      cachedToken = { token, expiresAtMs };
      return token;
    } finally {
      inFlightToken = null;
    }
  })();

  return inFlightToken;
}

function useAuthLoadingTimeout(isLoading: boolean): boolean {
  const [authTimedOut, setAuthTimedOut] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      if (!authTimedOut) return;
      const resetTimer = globalThis.setTimeout(() => setAuthTimedOut(false), 0);
      return () => globalThis.clearTimeout(resetTimer);
    }

    if (authTimedOut) return;

    const timer = globalThis.setTimeout(() => {
      setAuthTimedOut(true);
    }, AUTH_LOADING_TIMEOUT_MS);

    return () => globalThis.clearTimeout(timer);
  }, [isLoading, authTimedOut]);

  return authTimedOut;
}

function useBootstrapTimeout({
  active,
  onTimeout,
}: {
  active: boolean;
  onTimeout: () => void;
}) {
  useEffect(() => {
    if (!active) return;
    const timer = globalThis.setTimeout(onTimeout, BOOTSTRAP_TIMEOUT_MS);
    return () => globalThis.clearTimeout(timer);
  }, [active, onTimeout]);
}

async function bootstrapAccount({
  email,
  isCancelled,
  name,
  pickActive,
  setBootstrapped,
  setError,
  setLoadingLabel,
  setProfile,
  setProjects,
}: {
  email: string;
  isCancelled: () => boolean;
  name: string | null;
  pickActive: PickActiveProject;
  setBootstrapped: (value: boolean) => void;
  setError: (value: string | null) => void;
  setLoadingLabel: (value: string | null) => void;
  setProfile: (value: UserProfile | null) => void;
  setProjects: (value: Project[]) => void;
}) {
  try {
    setLoadingLabel("Requesting API token");
    const token = await getAccessTokenWithTimeout();
    if (isCancelled()) return;
    setLoadingLabel("Syncing account");
    const profile = await api.syncUser(token, { email, name });
    if (isCancelled()) return;
    setLoadingLabel("Loading projects");
    const list = await api.projects(token);
    if (isCancelled()) return;
    setProfile(profile);
    setProjects(list);
    pickActive(list);
    setError(null);
    setLoadingLabel(null);
  } catch (error) {
    if (!isCancelled()) {
      setError(error instanceof Error ? error.message : String(error));
      setLoadingLabel(null);
    }
  } finally {
    if (!isCancelled()) setBootstrapped(true);
  }
}

function sessionStatus({
  authTimedOut,
  bootstrapped,
  error,
  isLoading,
  seeded,
  userReady,
}: {
  authTimedOut: boolean;
  bootstrapped: boolean;
  error: string | null;
  isLoading: boolean;
  seeded: boolean;
  userReady: boolean;
}): Status {
  if (authTimedOut) return "error";
  if (seeded && !error) return "ready";
  if (isLoading || (userReady && !bootstrapped)) return "loading";
  if (!userReady) return "anonymous";
  return error ? "error" : "ready";
}

export function SessionProvider({
  children,
  initialProjects,
  initialActiveProjectId = null,
}: {
  children: React.ReactNode;
  // When the server bootstrap resolves projects, they seed the provider so the
  // first paint is "ready" and the client skips its sync/projects waterfall.
  initialProjects?: Project[];
  initialActiveProjectId?: string | null;
}) {
  const seeded = Boolean(initialProjects && initialProjects.length > 0);
  const auth = useUser();
  const e2eUser = e2eAuthUser();
  const user = e2eUser ?? auth.user;
  const isLoading = e2eUser ? false : auth.isLoading;
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [projects, setProjects] = useState<Project[]>(initialProjects ?? []);
  const [activeProjectId, setActive] = useState<string | null>(initialActiveProjectId);
  const [bootstrapped, setBootstrapped] = useState(seeded);
  const [error, setError] = useState<string | null>(null);
  const [loadingLabel, setLoadingLabel] = useState<string | null>(seeded ? null : "Checking session");
  const authTimedOut = useAuthLoadingTimeout(isLoading);

  const getToken = useCallback(() => getAccessTokenWithTimeout(), []);

  const setActiveProjectId = useCallback((id: string) => {
    writeActiveProjectCookie(id);
    setActive(id);
  }, []);

  const pickActive = useCallback((list: Project[]) => {
    const storedProject = list.find((p) => p.id === readActiveProjectCookie());
    // Prefer a demo-tenant project (org.is_demo) so the dashboard lands on the
    // seeded narrative, keyed off the structural flag rather than a hard-coded
    // project name. Falls through to the stored choice, then the first project.
    // This must match pickActiveProject in lib/serverSession.ts.
    const demoProject = list.find((p) => p.is_demo);
    const nextProject = demoProject ?? storedProject ?? list[0] ?? null;
    if (nextProject) writeActiveProjectCookie(nextProject.id);
    setActive(nextProject?.id ?? null);
  }, []);

  const refreshProjects = useCallback(async () => {
    const list = await api.projects(await getAccessTokenWithTimeout());
    setProjects(list);
    pickActive(list);
  }, [pickActive]);

  const onBootstrapTimeout = useCallback(() => {
    setError("Account bootstrap timed out. Try resetting your session, then log in again.");
    setBootstrapped(true);
  }, []);

  useBootstrapTimeout({
    active: Boolean(!seeded && !authTimedOut && !isLoading && user && !bootstrapped),
    onTimeout: onBootstrapTimeout,
  });

  // On login: provision the user (sync) and load their projects. Skipped when the
  // server already seeded projects. Logout is a full-page nav, so stale state
  // clears on its own.
  useEffect(() => {
    if (seeded || isLoading || authTimedOut || !user) return;
    let cancelled = false;
    void bootstrapAccount({
      email: user.email ?? "",
      isCancelled: () => cancelled,
      name: user.name ?? null,
      pickActive,
      setBootstrapped,
      setError,
      setLoadingLabel,
      setProfile,
      setProjects,
    });
    return () => {
      cancelled = true;
    };
  }, [seeded, user, isLoading, authTimedOut, pickActive]);

  // On the seeded path the provider is already "ready", but the profile (org
  // name, first-project orgId) still needs the user sync. Run it in the
  // background without blocking first paint; provisioning is idempotent.
  useEffect(() => {
    if (!seeded || !user || profile) return;
    let cancelled = false;
    void (async () => {
      try {
        const synced = await api.syncUser(await getAccessTokenWithTimeout(), {
          email: user.email ?? "",
          name: user.name ?? null,
        });
        if (!cancelled) setProfile(synced);
      } catch {
        // Non-fatal: header falls back to project/email until this lands.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [seeded, user, profile]);

  const status = sessionStatus({ authTimedOut, bootstrapped, error, isLoading, seeded, userReady: Boolean(user) });
  const visibleError = authTimedOut
    ? "Authentication is taking too long to load. Try signing out and signing in again."
    : error;
  const visibleLoadingLabel = authTimedOut ? null : loadingLabel;

  return (
    <SessionContext.Provider
      value={{
        status,
        profile,
        projects,
        activeProjectId,
        setActiveProjectId,
        refreshProjects,
        getToken,
        error: visibleError,
        loadingLabel: visibleLoadingLabel,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
