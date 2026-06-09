"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { getAccessToken, useUser } from "@auth0/nextjs-auth0";
import { api } from "@/lib/api";
import type { Project, UserProfile } from "@/lib/types";

const ACTIVE_PROJECT_KEY = "varsten_active_project";

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
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useUser();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActive] = useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getToken = useCallback(() => getAccessToken(), []);

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
    const list = await api.projects(await getAccessToken());
    setProjects(list);
    pickActive(list);
  }, [pickActive]);

  // On login: provision the user (sync) and load their projects. Logout is a
  // full-page nav, so stale state clears on its own.
  useEffect(() => {
    if (isLoading || !user) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getAccessToken();
        const p = await api.syncUser(token, {
          email: user.email ?? "",
          name: user.name ?? null,
        });
        const list = await api.projects(token);
        if (cancelled) return;
        setProfile(p);
        setProjects(list);
        pickActive(list);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, isLoading, pickActive]);

  const status: Status =
    isLoading || (!!user && !bootstrapped)
      ? "loading"
      : !user
        ? "anonymous"
        : error
          ? "error"
          : "ready";

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
        error,
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
