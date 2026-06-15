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
import type { Project, UserProfile } from "@/lib/types";

const ACTIVE_PROJECT_KEY = "varsten_active_project";
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

async function getAccessTokenWithTimeout(): Promise<string> {
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

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useUser();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActive] = useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authTimedOut, setAuthTimedOut] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState<string | null>("Checking session");

  const getToken = useCallback(() => getAccessTokenWithTimeout(), []);

  const setActiveProjectId = useCallback((id: string) => {
    localStorage.setItem(ACTIVE_PROJECT_KEY, id);
    setActive(id);
  }, []);

  const pickActive = useCallback((list: Project[]) => {
    const stored = localStorage.getItem(ACTIVE_PROJECT_KEY);
    const storedProject = list.find((p) => p.id === stored);
    // Prefer a demo-tenant project (org.is_demo) so the dashboard lands on the
    // seeded narrative, keyed off the structural flag rather than a hard-coded
    // project name. Falls through to the stored choice, then the first project.
    const demoProject = list.find((p) => p.is_demo);
    const nextProject = demoProject ?? storedProject ?? list[0] ?? null;
    if (nextProject) localStorage.setItem(ACTIVE_PROJECT_KEY, nextProject.id);
    setActive(nextProject?.id ?? null);
  }, []);

  const refreshProjects = useCallback(async () => {
    const list = await api.projects(await getAccessTokenWithTimeout());
    setProjects(list);
    pickActive(list);
  }, [pickActive]);

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

  useEffect(() => {
    if (authTimedOut || isLoading || !user || bootstrapped) return;

    const timer = globalThis.setTimeout(() => {
      setError("Account bootstrap timed out. Try resetting your session, then log in again.");
      setBootstrapped(true);
    }, BOOTSTRAP_TIMEOUT_MS);

    return () => globalThis.clearTimeout(timer);
  }, [authTimedOut, bootstrapped, isLoading, user]);

  // On login: provision the user (sync) and load their projects. Logout is a
  // full-page nav, so stale state clears on its own.
  useEffect(() => {
    if (isLoading || authTimedOut || !user) return;
    let cancelled = false;
    (async () => {
      try {
        setLoadingLabel("Requesting API token");
        const token = await getAccessTokenWithTimeout();
        if (cancelled) return;
        setLoadingLabel("Syncing account");
        const p = await api.syncUser(token, {
          email: user.email ?? "",
          name: user.name ?? null,
        });
        if (cancelled) return;
        setLoadingLabel("Loading projects");
        const list = await api.projects(token);
        if (cancelled) return;
        setProfile(p);
        setProjects(list);
        pickActive(list);
        setError(null);
        setLoadingLabel(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoadingLabel(null);
        }
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, isLoading, authTimedOut, pickActive]);

  const status: Status =
    authTimedOut
      ? "error"
      : isLoading || (!!user && !bootstrapped)
      ? "loading"
      : !user
        ? "anonymous"
        : error
          ? "error"
          : "ready";
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
