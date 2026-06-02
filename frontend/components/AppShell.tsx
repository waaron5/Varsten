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
      { href: "/engine/recommendations", match: "/engine", label: "Engine", icon: "M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z M9 12l2 2 4-5", badge: "5" },
      { href: "/guardrails/quality", match: "/guardrails", label: "Guardrails", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z M9 12l2 2 4-5" },
      { href: "/proof/savings", match: "/proof", label: "Proof", icon: "M4 19.5V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-1.5z M8 7h6 M8 11h8 M8 15h5" },
    ],
  },
  {
    label: "Explore",
    items: [
      { href: "/analysis/spend", match: "/analysis", label: "Analysis", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
      { href: "/reports", match: "/reports", label: "Reports", icon: "M7 3h7l5 5v13H7V3z M14 3v6h5 M10 13h6 M10 17h6" },
      { href: "/admin/connections", match: "/admin", label: "Admin", icon: "M14 7a4 4 0 1 1-3.9 5H6v3H3v-3l3.1-3.1A4 4 0 0 1 14 7z M15 8.5h.01" },
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
