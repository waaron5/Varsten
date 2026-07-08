"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@auth0/nextjs-auth0";
import { useSession } from "./session";
import { useEntitlements } from "./entitlements";
import { DashboardChromeProvider } from "./dashboardChrome";
import { DashboardCrumb, DashboardTopbarControls } from "./dashboard/DashboardTopbarControls";
import type { Project, UserProfile } from "@/lib/types";

// Name of the cookie that persists the sidebar collapsed state. Read on the server
// in the root layout (for a hydration-safe first paint) and written here on toggle.
export const SIDEBAR_COOKIE = "cc_sidebar";

const NAV_GROUPS: {
  label: string;
  items: { href: string; match: string; label: string; icon: string; badge?: string }[];
}[] = [
  {
    label: "Operate",
    items: [
      { href: "/dashboard", match: "/dashboard", label: "Dashboard", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
      { href: "/engine/levers", match: "/engine", label: "Engine", icon: "M9 9h6v6H9z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3 M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" },
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
  "/dashboard": { title: "Savings Overview", crumb: "Overview" },
  "/engine": { title: "Engine", crumb: "Engine / Levers" },
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
  "/onboarding": { title: "Setup", crumb: "Setup" },
  "/setup": { title: "Setup", crumb: "Project / Setup" },
  "/settings": { title: "Settings", crumb: "Project / Settings" },
};

type NavItem = { href: string; match: string; label: string; icon: string; badge?: string };

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
  const first = parts[0]?.[0] ?? "V";
  const second = parts[1]?.[0] ?? "";
  return `${first}${second}`.toUpperCase();
}

function isNavItemActive(item: NavItem, pathname: string): boolean {
  return pathname.startsWith(item.match);
}

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = isNavItemActive(item, pathname);
  return (
    <Link
      href={item.href}
      className={`nav-item${active ? " active" : ""}`}
      aria-label={item.label}
      data-label={item.label}
    >
      <Icon path={item.icon} />
      <span>{item.label}</span>
      {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
    </Link>
  );
}

function NavGroup({ group, pathname }: { group: { label: string; items: NavItem[] }; pathname: string }) {
  return (
    <div className="nav-group">
      {group.items.map((item) => <NavLink key={item.href} item={item} pathname={pathname} />)}
    </div>
  );
}

function AccountPanel({
  accountOpen,
  displayName,
  isSidebarCollapsed,
  isLoading,
  orgName,
  setAccountOpen,
  userReady,
}: {
  accountOpen: boolean;
  displayName: string;
  isSidebarCollapsed: boolean;
  isLoading: boolean;
  orgName: string;
  setAccountOpen: Dispatch<SetStateAction<boolean>>;
  userReady: boolean;
}) {
  const accountRef = useRef<HTMLDivElement | null>(null);
  const { loading: entitlementsLoading, planTier, isPerformance, observeOnly } = useEntitlements();
  const plan = accountPlanState({ entitlementsLoading, isPerformance, observeOnly, planTier });
  useAccountMenuDismiss(accountOpen, accountRef, setAccountOpen);

  if (isLoading) return null;
  if (!userReady) return <a href="/auth/login" className="account-login">Log in</a>;
  return (
    <div className="account-wrap" ref={accountRef}>
      <AccountButton
        accountOpen={accountOpen}
        displayName={displayName}
        isSidebarCollapsed={isSidebarCollapsed}
        onToggle={() => setAccountOpen((open) => !open)}
        orgName={orgName}
      />
      {accountOpen ? <AccountMenu isPerformance={isPerformance} onClose={() => setAccountOpen(false)} plan={plan} /> : null}
    </div>
  );
}

function accountPlanState({
  entitlementsLoading,
  isPerformance,
  observeOnly,
  planTier,
}: {
  entitlementsLoading: boolean;
  isPerformance: boolean;
  observeOnly: boolean;
  planTier: string | null;
}) {
  return {
    actionHref: isPerformance ? "/admin/billing-security" : "/upgrade",
    actionLabel: isPerformance ? "Billing & plan" : "Upgrade to Optimize",
    detail: isPerformance && !observeOnly ? "Optimization enabled" : "Observe-only",
    name: isPerformance ? "Optimize" : "Free",
    show: !entitlementsLoading && planTier !== null,
  };
}

function useAccountMenuDismiss(
  accountOpen: boolean,
  accountRef: RefObject<HTMLDivElement | null>,
  setAccountOpen: Dispatch<SetStateAction<boolean>>,
) {
  useEffect(() => {
    if (!accountOpen) return;

    const closeIfOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && accountRef.current?.contains(target)) return;
      setAccountOpen(false);
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountOpen(false);
    };

    document.addEventListener("pointerdown", closeIfOutside, true);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside, true);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [accountOpen, accountRef, setAccountOpen]);
}

function AccountButton({
  accountOpen,
  displayName,
  isSidebarCollapsed,
  onToggle,
  orgName,
}: {
  accountOpen: boolean;
  displayName: string;
  isSidebarCollapsed: boolean;
  onToggle: () => void;
  orgName: string;
}) {
  return (
    <button
      className="account-button"
      type="button"
      aria-haspopup="menu"
      aria-expanded={accountOpen}
      aria-label={`Account: ${displayName}`}
      title={isSidebarCollapsed ? `Account: ${displayName}` : undefined}
      onClick={onToggle}
    >
      <span className="account-avatar">{initials(displayName)}</span>
      <span className="account-copy">
        <span className="account-name">{displayName}</span>
        <span className="account-org">{orgName}</span>
      </span>
      <svg className="account-options-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 9l4-4 4 4M16 15l-4 4-4-4" />
      </svg>
    </button>
  );
}

function AccountMenu({
  isPerformance,
  onClose,
  plan,
}: {
  isPerformance: boolean;
  onClose: () => void;
  plan: ReturnType<typeof accountPlanState>;
}) {
  return (
    <div className="account-menu" role="menu">
      {plan.show ? <AccountPlanMenuItem isPerformance={isPerformance} onClose={onClose} plan={plan} /> : null}
      {/* Auth routes must use <a>, not <Link>, to avoid client-side routing. */}
      <a href="/auth/logout" className="account-menu-item" role="menuitem">Log out</a>
    </div>
  );
}

function AccountPlanMenuItem({
  isPerformance,
  onClose,
  plan,
}: {
  isPerformance: boolean;
  onClose: () => void;
  plan: ReturnType<typeof accountPlanState>;
}) {
  return (
    <>
      <div className="account-menu-section" role="group" aria-label="Workspace">
        <div className="account-menu-kicker">Workspace</div>
        <div className="account-plan" role="presentation">
          <span className="account-plan-label">Plan: {plan.name}</span>
          <span className="account-plan-detail">{plan.detail}</span>
        </div>
      </div>
      <Link
        href={plan.actionHref}
        className={`account-menu-item${isPerformance ? "" : " upgrade"}`}
        role="menuitem"
        onClick={onClose}
      >
        {plan.actionLabel}
      </Link>
      <div className="account-menu-divider" role="separator" />
    </>
  );
}

function Sidebar({
  accountOpen,
  displayName,
  isCollapsed,
  isLoading,
  onToggleCollapse,
  orgName,
  pathname,
  setAccountOpen,
  userReady,
}: {
  accountOpen: boolean;
  displayName: string;
  isCollapsed: boolean;
  isLoading: boolean;
  onToggleCollapse: () => void;
  orgName: string;
  pathname: string;
  setAccountOpen: Dispatch<SetStateAction<boolean>>;
  userReady: boolean;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <Link href="/dashboard" className="brand-link" aria-label="Go to Dashboard">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/varsten-logo.svg" alt="Varsten" className="brand-logo" />
        </Link>
        <button
          type="button"
          className="sidebar-toggle"
          aria-label={isCollapsed ? "Expand navigation" : "Collapse navigation"}
          aria-expanded={!isCollapsed}
          title={isCollapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={onToggleCollapse}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden="true">
            <path d="M5 7h14M5 12h14M5 17h14" />
          </svg>
        </button>
      </div>
      <nav className="nav">
        {NAV_GROUPS.map((group) => <NavGroup key={group.label} group={group} pathname={pathname} />)}
      </nav>
      <div className="side-account">
        <AccountPanel
          accountOpen={accountOpen}
          displayName={displayName}
          isSidebarCollapsed={isCollapsed}
          isLoading={isLoading}
          orgName={orgName}
          setAccountOpen={setAccountOpen}
          userReady={userReady}
        />
      </div>
    </aside>
  );
}

function Topbar({ route, isDashboard }: { route: { title: string; crumb: string }; isDashboard: boolean }) {
  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{route.title}</h1>
        {isDashboard ? <DashboardCrumb /> : <div className="crumb">{route.crumb}</div>}
      </div>
      {isDashboard && <DashboardTopbarControls />}
    </header>
  );
}

function firstProject(projects: Project[]): Project | null {
  return projects.length > 0 ? projects[0] : null;
}

function activeProjectFor(projects: Project[], activeProjectId: string | null): Project | null {
  return projects.find((project) => project.id === activeProjectId) || firstProject(projects);
}

function activeOrgName(profile: UserProfile | null, project: Project | null): string | null {
  const organizations = profile?.organizations || [];
  const organization = organizations.find((org) => org.id === project?.organization_id) || organizations[0];
  return organization?.name || null;
}

function accountNames({
  profile,
  project,
  userEmail,
  userName,
}: {
  profile: UserProfile | null;
  project: Project | null;
  userEmail?: string | null;
  userName?: string | null;
}) {
  return {
    displayName: profile?.name || userName || userEmail || "Varsten user",
    orgName: activeOrgName(profile, project) || project?.name || "Varsten workspace",
  };
}

export function AppShell({
  children,
  initialCollapsed = false,
}: {
  children: React.ReactNode;
  initialCollapsed?: boolean;
}) {
  const pathname = usePathname();
  const { user, isLoading } = useUser();
  const { activeProjectId, profile, projects } = useSession();
  const [accountOpen, setAccountOpen] = useState(false);
  // Seeded from the server-read cookie, so the first client render matches the SSR
  // markup (no hydration mismatch, no expand-then-collapse flash).
  const [sidebarCollapsed, setSidebarCollapsed] = useState(initialCollapsed);
  const hasMounted = useRef(false);
  const currentRoute = routeLabel(pathname);
  const activeProject = activeProjectFor(projects, activeProjectId);
  const { displayName, orgName } = accountNames({
    profile,
    project: activeProject,
    userEmail: user?.email,
    userName: user?.name,
  });
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((collapsed) => !collapsed);
    setAccountOpen((open) => (open ? false : open));
  }, []);

  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true;
      return;
    }

    const timer = window.setTimeout(() => {
      // Keep the synchronous cookie write out of the click frame and sidebar
      // width transition; the server reads this on the following request.
      document.cookie = `${SIDEBAR_COOKIE}=${sidebarCollapsed ? "collapsed" : "expanded"}; path=/; max-age=31536000; samesite=lax`;
    }, 240);

    return () => window.clearTimeout(timer);
  }, [sidebarCollapsed]);

  return (
    <DashboardChromeProvider>
      <div className={`app${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
        <Sidebar
          accountOpen={accountOpen}
          displayName={displayName}
          isCollapsed={sidebarCollapsed}
          isLoading={isLoading}
          onToggleCollapse={toggleSidebar}
          orgName={orgName}
          pathname={pathname}
          setAccountOpen={setAccountOpen}
          userReady={!!user}
        />
        <div className="main">
          <Topbar route={currentRoute} isDashboard={pathname === "/dashboard"} />
          <div className="content">{children}</div>
        </div>
      </div>
    </DashboardChromeProvider>
  );
}
