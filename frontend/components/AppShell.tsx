"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
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
      { href: "/guardrails/quality", match: "/guardrails", label: "Guardrails", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
      { href: "/proof/savings", match: "/proof", label: "Proof", icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M8.5 12.5l2.5 2.5 4.5-5" },
    ],
  },
  {
    label: "Explore",
    items: [
      { href: "/analysis/spend", match: "/analysis", label: "Analysis", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
      { href: "/reports", match: "/reports", label: "Reports", icon: "M7 3h7l5 5v13H7V3z M14 3v6h5 M10 13h6 M10 17h6" },
      { href: "/admin/connections", match: "/admin", label: "Settings", icon: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4a1.65 1.65 0 0 0 1-1.51V2a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15.08 4a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.63.78 1 1.51 1H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z" },
    ],
  },
];

const ROUTE_LABELS: Record<string, { title: string; crumb: string }> = {
  "/command-center": { title: "Command Center", crumb: "Home" },
  "/engine": { title: "Engine", crumb: "Engine / Recommendations" },
  "/engine/recommendations": { title: "Engine", crumb: "Engine / Recommendations" },
  "/engine/levers": { title: "Engine", crumb: "Engine / Levers" },
  "/engine/automation": { title: "Engine", crumb: "Engine / Automation" },
  "/guardrails": { title: "Guardrails", crumb: "Guardrails / Quality" },
  "/guardrails/quality": { title: "Guardrails", crumb: "Guardrails / Quality" },
  "/guardrails/budgets": { title: "Guardrails", crumb: "Guardrails / Budgets" },
  "/guardrails/alerts": { title: "Guardrails", crumb: "Guardrails / Alerts" },
  "/proof": { title: "Proof", crumb: "Proof / Savings" },
  "/proof/savings": { title: "Proof", crumb: "Proof / Savings" },
  "/proof/attribution": { title: "Proof", crumb: "Proof / Attribution" },
  "/proof/data-quality": { title: "Proof", crumb: "Proof / Data Quality" },
  "/analysis": { title: "Analysis", crumb: "Analysis / Spend" },
  "/analysis/spend": { title: "Analysis", crumb: "Analysis / Spend" },
  "/analysis/customers": { title: "Analysis", crumb: "Analysis / Customers" },
  "/analysis/models": { title: "Analysis", crumb: "Analysis / Models" },
  "/reports": { title: "Executive Report", crumb: "Reports" },
  "/admin": { title: "Settings", crumb: "Settings / Connections" },
  "/admin/connections": { title: "Settings", crumb: "Settings / Connections" },
  "/admin/team": { title: "Settings", crumb: "Settings / Team" },
  "/admin/billing-security": { title: "Settings", crumb: "Settings / Billing & Security" },
  "/breakdowns": { title: "Breakdowns", crumb: "Explore / Breakdowns" },
  "/explorer": { title: "Explorer", crumb: "Explore / Usage Events" },
  "/setup": { title: "Setup", crumb: "Project / Setup" },
  "/settings": { title: "Settings", crumb: "Project / Settings" },
};

function routeLabel(pathname: string): { title: string; crumb: string } {
  if (pathname.startsWith("/reports/")) return { title: "Executive Report", crumb: "Reports / Shared View" };
  return ROUTE_LABELS[pathname] ?? { title: "Varsten", crumb: "Home" };
}

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

function initials(nameOrEmail: string | null | undefined): string {
  const value = nameOrEmail?.trim();
  if (!value) return "VA";
  const clean = value.includes("@") ? value.split("@")[0] : value;
  const parts = clean.split(/\s+|[._-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "V").concat(parts[1]?.[0] ?? "").toUpperCase();
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, isLoading } = useUser();
  const { activeProjectId, profile, projects } = useSession();
  const [accountOpen, setAccountOpen] = useState(false);
  const currentRoute = routeLabel(pathname);
  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0] ?? null;
  const activeOrg = profile?.organizations.find((org) => org.id === activeProject?.organization_id) ?? profile?.organizations[0] ?? null;
  const displayName = profile?.name ?? user?.name ?? user?.email ?? "Varsten user";
  const orgName = activeOrg?.name ?? activeProject?.name ?? "Varsten workspace";

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
        <div className="side-account">
          {!isLoading && user ? (
            <div className="account-wrap">
              <button
                className="account-button"
                type="button"
                aria-haspopup="menu"
                aria-expanded={accountOpen}
                onClick={() => setAccountOpen((open) => !open)}
              >
                <span className="account-avatar">{initials(displayName)}</span>
                <span className="account-copy">
                  <span className="account-name">{displayName}</span>
                  <span className="account-org">{orgName}</span>
                </span>
                <span className="account-dots" aria-hidden="true">•••</span>
              </button>
              {accountOpen ? (
                <div className="account-menu" role="menu">
                  {/* Auth routes must use <a>, not <Link>, to avoid client-side routing. */}
                  <a href="/auth/logout" className="account-menu-item" role="menuitem">Log out</a>
                </div>
              ) : null}
            </div>
          ) : !isLoading ? (
            <a href="/auth/login" className="account-login">Log in</a>
          ) : null}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{currentRoute.title}</h1>
            <div className="crumb">{currentRoute.crumb}</div>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
