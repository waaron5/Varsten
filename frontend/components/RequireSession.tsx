"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "./session";

// Gate for dashboard pages: requires an Auth0 session and an active project.
// A brand-new user has a bootstrapped org but no project, so we offer inline
// project creation to keep the first-run flow moving.
export function RequireSession({ children }: { children: React.ReactNode }) {
  const { status, profile, projects, error, loadingLabel } = useSession();
  const loginHref = currentLoginHref();

  if (status === "loading") {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
        <div className="empty">
          <div className="spinner" />
          <div className="es">{loadingLabel ?? "Loading account"}</div>
        </div>
      </div>
    );
  }

  if (status === "anonymous") {
    return (
      <div className="view">
        <div className="empty">
          <div className="et">Sign in to view your dashboard</div>
          <div className="es">Varsten uses your account to scope spend and usage to your projects.</div>
          <a href={loginHref} className="btn primary">Log in</a>
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="view">
        <div className="empty">
          <div className="et">Could not load your account</div>
          <div className="es">{error}</div>
          <div className="empty-actions">
            <a href="/auth/logout" className="btn">Reset session</a>
            <a href={loginHref} className="btn primary">Log in</a>
          </div>
        </div>
      </div>
    );
  }

  if (projects.length === 0) {
    return <FirstProject orgId={profile?.organizations[0]?.id} />;
  }

  return <>{children}</>;
}

function currentLoginHref(): string {
  if (typeof window === "undefined") return "/auth/login";
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `/auth/login?returnTo=${encodeURIComponent(returnTo)}`;
}

function FirstProject({ orgId }: { orgId: string | undefined }) {
  const { refreshProjects, getToken } = useSession();
  const [name, setName] = useState("Production");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async () => {
    if (!orgId || !name.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.createProject(await getToken(), orgId, name.trim());
      await refreshProjects();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <div className="empty">
        <div className="et">Create your first project</div>
        <div className="es">A project holds an API key and the usage events sent to it.</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            style={{ width: 220 }}
          />
          <button className="btn primary" disabled={busy || !orgId} onClick={create}>
            {busy ? "Creating…" : "Create project"}
          </button>
        </div>
        {err && <div className="es" style={{ color: "var(--neg)" }}>{err}</div>}
      </div>
    </div>
  );
}
