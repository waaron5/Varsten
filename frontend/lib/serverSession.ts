import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";
import { auth0 } from "./auth0";
import { api } from "./api";
import { ACTIVE_PROJECT_COOKIE } from "./projectCookie";
import type { Project } from "./types";

interface ServerBootstrap {
  token: string;
  projects: Project[];
  activeProjectId: string | null;
}

// Must mirror pickActive in components/session.tsx so the server resolves the
// same active project the client would, avoiding a hydration mismatch: keep a
// stored project choice first, then fall back to the seeded demo, then the first
// project.
function pickActiveProject(list: Project[], cookieId: string | undefined): Project | null {
  const stored = list.find((p) => p.id === cookieId);
  const demo = list.find((p) => p.is_demo);
  return stored ?? demo ?? list[0] ?? null;
}

// Resolves token + projects + active project on the server so the first paint
// can render real data and the client can skip its bootstrap waterfall. Cached
// per request via React.cache so the root layout and a page can both call it
// without double-fetching. Returns null when there is no session or the API is
// unreachable / the user is not yet provisioned, in which case callers fall back
// to the client bootstrap path (which also provisions a brand-new user).
export const loadServerBootstrap = cache(async (): Promise<ServerBootstrap | null> => {
  const session = await auth0.getSession();
  if (!session?.user) return null;
  try {
    const { token } = await auth0.getAccessToken();
    const projects = await api.projects(token);
    if (projects.length === 0) return null;
    const cookieId = (await cookies()).get(ACTIVE_PROJECT_COOKIE)?.value;
    const active = pickActiveProject(projects, cookieId);
    return { token, projects, activeProjectId: active?.id ?? null };
  } catch {
    return null;
  }
});
