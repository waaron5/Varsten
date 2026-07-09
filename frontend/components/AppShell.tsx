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

// Existing cookie name, new values. Old "collapsed" is read as closed and old
// "expanded" is read as open by app/layout.tsx for a hydration-safe migration.
export const SIDEBAR_COOKIE = "cc_sidebar";

type NavItem = { href: string; match: string; label: string; icon: string };
type NavSection = { items: NavItem[] };

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { href: "/dashboard", match: "/dashboard", label: "Dashboard", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
      { href: "/engine/levers", match: "/engine", label: "Engine", icon: "M9 9h6v6H9z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3 M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" },
      { href: "/guardrails/quality", match: "/guardrails", label: "Guardrails", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
    ],
  },
  {
    items: [
      { href: "/proof/savings", match: "/proof", label: "Savings Proof", icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M8.5 12.5l2.5 2.5 4.5-5" },
      { href: "/analysis/spend", match: "/analysis", label: "Spend Analysis", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
      { href: "/admin/connections", match: "/admin", label: "Settings", icon: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4a1.65 1.65 0 0 0 1-1.51V2a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15.08 4a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.63.78 1 1.51 1H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z" },
    ],
  },
];

const ROUTE_LABELS: Record<string, { title: string; crumb: string }> = {
  "/dashboard": { title: "Dashboard", crumb: "Overview" },
  "/engine": { title: "Engine", crumb: "Levers" },
  "/engine/recommendations": { title: "Engine", crumb: "Recommendations" },
  "/engine/levers": { title: "Engine", crumb: "Levers" },
  "/engine/automation": { title: "Engine", crumb: "Automation" },
  "/guardrails": { title: "Guardrails", crumb: "Quality" },
  "/guardrails/quality": { title: "Guardrails", crumb: "Quality" },
  "/guardrails/budgets": { title: "Guardrails", crumb: "Budgets" },
  "/guardrails/alerts": { title: "Guardrails", crumb: "Alerts" },
  "/proof": { title: "Savings Proof", crumb: "Savings" },
  "/proof/savings": { title: "Savings Proof", crumb: "Savings" },
  "/proof/attribution": { title: "Savings Proof", crumb: "Attribution" },
  "/proof/data-quality": { title: "Savings Proof", crumb: "Data Quality" },
  "/analysis": { title: "Spend Analysis", crumb: "Spend" },
  "/analysis/spend": { title: "Spend Analysis", crumb: "Spend" },
  "/analysis/customers": { title: "Spend Analysis", crumb: "Customers" },
  "/analysis/models": { title: "Spend Analysis", crumb: "Models" },
  "/reports": { title: "Executive Report", crumb: "Reports" },
  "/admin": { title: "Settings", crumb: "Connections" },
  "/admin/connections": { title: "Settings", crumb: "Connections" },
  "/admin/team": { title: "Settings", crumb: "Team" },
  "/admin/billing-security": { title: "Settings", crumb: "Billing & Security" },
  "/breakdowns": { title: "Breakdowns", crumb: "Breakdowns" },
  "/explorer": { title: "Explorer", crumb: "Usage Events" },
  "/onboarding": { title: "Setup", crumb: "Setup" },
  "/setup": { title: "Setup", crumb: "Setup" },
  "/settings": { title: "Settings", crumb: "Settings" },
};

function routeLabel(pathname: string): { title: string; crumb: string } {
  if (pathname.startsWith("/reports/")) return { title: "Executive Report", crumb: "Shared View" };
  return ROUTE_LABELS[pathname] ?? { title: "Varsten", crumb: "Home" };
}

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

function MoreHorizontalIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h.01M12 12h.01M19 12h.01" />
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

function NavLink({ item, open, pathname }: { item: NavItem; open: boolean; pathname: string }) {
  const active = isNavItemActive(item, pathname);
  return (
    <Link
      href={item.href}
      className={`lv-nav-item${active ? " active" : ""}`}
      aria-current={active ? "page" : undefined}
      tabIndex={open ? 0 : -1}
    >
      <Icon path={item.icon} />
      <span>{item.label}</span>
    </Link>
  );
}

function NavSection({ open, pathname, section }: { open: boolean; pathname: string; section: NavSection }) {
  return (
    <div className="lv-nav-section">
      <ul className="lv-nav-list">
        {section.items.map((item) => (
          <li key={item.href}>
            <NavLink item={item} open={open} pathname={pathname} />
          </li>
        ))}
      </ul>
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

function AccountPanel({
  accountOpen,
  displayName,
  isLoading,
  navOpen,
  setAccountOpen,
  userReady,
}: {
  accountOpen: boolean;
  displayName: string;
  isLoading: boolean;
  navOpen: boolean;
  setAccountOpen: Dispatch<SetStateAction<boolean>>;
  userReady: boolean;
}) {
  const accountRef = useRef<HTMLDivElement | null>(null);
  const { loading: entitlementsLoading, planTier, isPerformance, observeOnly } = useEntitlements();
  const plan = accountPlanState({ entitlementsLoading, isPerformance, observeOnly, planTier });
  useAccountMenuDismiss(accountOpen, accountRef, setAccountOpen);

  if (isLoading) return null;
  if (!userReady) return <a href="/auth/login" className="lv-account-login" tabIndex={navOpen ? 0 : -1}>Log in</a>;
  return (
    <div className="lv-account-wrap" ref={accountRef}>
      <button
        className="lv-account-button"
        type="button"
        aria-haspopup="menu"
        aria-expanded={accountOpen}
        aria-label={`Account: ${displayName}`}
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setAccountOpen((open) => !open)}
      >
        <span className="lv-account-avatar">{initials(displayName)}</span>
        <span className="lv-account-copy">
          <span className="lv-account-name">{displayName}</span>
        </span>
        <span className="lv-account-chevron" aria-hidden="true">
          <MoreHorizontalIcon />
        </span>
      </button>
      {accountOpen ? <AccountMenu isPerformance={isPerformance} onClose={() => setAccountOpen(false)} plan={plan} /> : null}
    </div>
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
    <div className="lv-account-menu" role="menu">
      {plan.show ? (
        <>
          <div className="lv-account-menu-section" role="group" aria-label="Workspace">
            <div className="lv-account-menu-kicker">Workspace</div>
            <div className="lv-account-plan">
              <span>Plan: {plan.name}</span>
              <small>{plan.detail}</small>
            </div>
          </div>
          <Link
            href={plan.actionHref}
            className={`lv-account-menu-item${isPerformance ? "" : " upgrade"}`}
            role="menuitem"
            onClick={onClose}
          >
            {plan.actionLabel}
          </Link>
          <div className="lv-account-menu-divider" role="separator" />
        </>
      ) : null}
      <a href="/auth/logout" className="lv-account-menu-item" role="menuitem">Log out</a>
    </div>
  );
}

function Sidebar({
  accountOpen,
  displayName,
  isLoading,
  navOpen,
  pathname,
  projectName,
  workspaceName,
  setAccountOpen,
  userReady,
}: {
  accountOpen: boolean;
  displayName: string;
  isLoading: boolean;
  navOpen: boolean;
  pathname: string;
  projectName: string;
  workspaceName: string;
  setAccountOpen: Dispatch<SetStateAction<boolean>>;
  userReady: boolean;
}) {
  return (
    <aside className="lv-sidebar" aria-label="Primary" aria-hidden={!navOpen}>
      <div className="lv-sidebar-inner">
        <div className="lv-brand">
          <div className="lv-brand-link" aria-label="Current workspace">
            <span className="lv-brand-code">{workspaceName}</span>
            <span className="lv-brand-name">{projectName}</span>
          </div>
        </div>
        <nav className="lv-nav">
          {NAV_SECTIONS.map((section) => (
            <NavSection key={section.items[0]?.href} open={navOpen} pathname={pathname} section={section} />
          ))}
        </nav>
        <div className="lv-side-account">
          <AccountPanel
            accountOpen={accountOpen}
            displayName={displayName}
            isLoading={isLoading}
            navOpen={navOpen}
            setAccountOpen={setAccountOpen}
            userReady={userReady}
          />
        </div>
      </div>
    </aside>
  );
}

function Topbar({
  isDashboard,
  navOpen,
  onToggleNav,
  route,
}: {
  isDashboard: boolean;
  navOpen: boolean;
  onToggleNav: () => void;
  route: { title: string; crumb: string };
}) {
  return (
    <header className="lv-topbar">
      <div className="lv-topbar-inner">
        <div className="lv-topbar-left">
          <button
            type="button"
            className="lv-nav-toggle"
            aria-label={navOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={navOpen}
            onClick={onToggleNav}
          >
            <MenuIcon />
          </button>
          <div className="lv-route-copy">
            {isDashboard ? (
              <div className="lv-route-eyebrow">
                Dashboard <span aria-hidden="true">·</span> <DashboardCrumb />
              </div>
            ) : (
              <>
                <div className="lv-route-eyebrow">{route.title}</div>
                <div className="lv-route-crumb">{route.crumb}</div>
              </>
            )}
          </div>
        </div>
        {isDashboard ? <DashboardTopbarControls /> : null}
      </div>
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

function shellNames({
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
    displayName: userEmail || profile?.name || userName || "Varsten user",
    projectName: project?.name || "Project",
    workspaceName: activeOrgName(profile, project) || "Workspace",
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
  const [navOpen, setNavOpen] = useState(!initialCollapsed);
  const hasMounted = useRef(false);
  const currentRoute = routeLabel(pathname);
  const activeProject = activeProjectFor(projects, activeProjectId);
  const { displayName, projectName, workspaceName } = shellNames({
    profile,
    project: activeProject,
    userEmail: user?.email,
    userName: user?.name,
  });
  const toggleNav = useCallback(() => {
    setNavOpen((open) => !open);
    setAccountOpen(false);
  }, []);

  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true;
      return;
    }

    const timer = window.setTimeout(() => {
      document.cookie = `${SIDEBAR_COOKIE}=${navOpen ? "open" : "closed"}; path=/; max-age=31536000; samesite=lax`;
    }, 180);

    return () => window.clearTimeout(timer);
  }, [navOpen]);

  return (
    <DashboardChromeProvider>
      <div className={`lv-app${navOpen ? " nav-open" : " nav-closed"}`}>
        <Sidebar
          accountOpen={accountOpen}
          displayName={displayName}
          isLoading={isLoading}
          navOpen={navOpen}
          pathname={pathname}
          projectName={projectName}
          setAccountOpen={setAccountOpen}
          userReady={!!user}
          workspaceName={workspaceName}
        />
        <div className="lv-main">
          <Topbar
            isDashboard={pathname === "/dashboard"}
            navOpen={navOpen}
            onToggleNav={toggleNav}
            route={currentRoute}
          />
          <div className="content">{children}</div>
        </div>
      </div>
    </DashboardChromeProvider>
  );
}
