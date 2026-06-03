"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@auth0/nextjs-auth0";
import { useSession } from "./session";

const NAV_GROUPS: {
  label: string;
  items: { href: string; match: string; label: string; icon: string; badge?: string }[];
}[] = [
  {
    label: "Operate",
    items: [
      { href: "/command-center", match: "/command-center", label: "Command Center", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
      { href: "/engine/recommendations", match: "/engine", label: "Engine", icon: "M9 9h6v6H9z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3 M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z", badge: "5" },
      { href: "/guardrails/quality", match: "/guardrails", label: "Guardrails", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z M9 12l2 2 4-5" },
      { href: "/proof/savings", match: "/proof", label: "Proof", icon: "M4 19.5V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-1.5z M8 7h6 M8 11h8 M8 15h5" },
    ],
  },
  {
    label: "Explore",
    items: [
      { href: "/analysis/spend", match: "/analysis", label: "Analysis", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
      { href: "/reports", match: "/reports", label: "Reports", icon: "M7 3h7l5 5v13H7V3z M14 3v6h5 M10 13h6 M10 17h6" },
      { href: "/admin/connections", match: "/admin", label: "Admin", icon: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4a1.65 1.65 0 0 0 1-1.51V2a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15.08 4a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.63.78 1 1.51 1H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z" },
    ],
  },
];

const ALL_NAV = NAV_GROUPS.flatMap((group) => group.items);

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, isLoading } = useUser();
  const { projects, activeProjectId, setActiveProjectId } = useSession();
  const current = ALL_NAV.find((n) => pathname.startsWith(n.match)) ?? ALL_NAV[0];
  const currentTab = pathname
    .split("/")
    .filter(Boolean)
    .slice(1)
    .join(" ")
    .replace("-", " ");

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/varsten-lockup-white.svg" alt="Varsten" className="brand-logo" />
        </div>
        <nav className="nav">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-group-label">{group.label}</div>
              {group.items.map((n) => {
                const active = pathname.startsWith(n.match);
                return (
                  <Link key={n.href} href={n.href} className={`nav-item${active ? " active" : ""}`}>
                    <Icon path={n.icon} />
                    <span>{n.label}</span>
                    {n.badge && <span className="nav-badge">{n.badge}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumb">
            <span>Varsten</span>
            <span className="sep">/</span>
            <b>{current.label}</b>
            {currentTab && (
              <>
                <span className="sep">/</span>
                <span className="crumb-tab">{currentTab}</span>
              </>
            )}
          </div>
          <div className="topbar-actions">
            {user && projects.length > 0 && (
              <select
                className="input"
                value={activeProjectId ?? ""}
                onChange={(e) => setActiveProjectId(e.target.value)}
                aria-label="Active project"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            )}
            {!isLoading &&
              (user ? (
                <>
                  <span className="pill neutral">{user.name ?? user.email}</span>
                  {/* Auth routes must use <a>, not <Link>, to avoid client-side routing. */}
                  <a href="/auth/logout" className="btn">Log out</a>
                </>
              ) : (
                <a href="/auth/login" className="btn primary">Log in</a>
              ))}
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
