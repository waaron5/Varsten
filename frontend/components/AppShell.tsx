"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { Dispatch, FormEvent, RefObject, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@auth0/nextjs-auth0";
import { useSession } from "./session";
import { useEntitlements } from "./entitlements";
import { DashboardChromeProvider } from "./dashboardChrome";
import { DashboardCrumb, DashboardTopbarControls } from "./dashboard/DashboardTopbarControls";
import { api } from "@/lib/api";
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
      { href: "/automation", match: "/automation", label: "Automation", icon: "M9 9h6v6H9z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3 M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" },
      { href: "/guardrails/quality", match: "/guardrails", label: "Guardrails", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
    ],
  },
  {
    items: [
      { href: "/analysis/spend", match: "/analysis", label: "AI spend", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
      { href: "/proof/savings", match: "/proof", label: "Savings", icon: "M5 6.4A7 2.4 0 1 1 19 6.4A7 2.4 0 1 1 5 6.4 M5 12A7 2.4 0 1 1 19 12A7 2.4 0 1 1 5 12 M5 17.6A7 2.4 0 1 1 19 17.6A7 2.4 0 1 1 5 17.6" },
      { href: "/admin/connections", match: "/admin", label: "Settings", icon: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4a1.65 1.65 0 0 0 1-1.51V2a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15.08 4a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.63.78 1 1.51 1H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z" },
    ],
  },
];

const ROUTE_LABELS: Record<string, { title: string; crumb: string }> = {
  "/dashboard": { title: "Dashboard", crumb: "Overview" },
  "/automation": { title: "Automation", crumb: "Levers" },
  "/engine": { title: "Automation", crumb: "Levers" },
  "/engine/recommendations": { title: "Automation", crumb: "Levers" },
  "/engine/levers": { title: "Automation", crumb: "Levers" },
  "/engine/automation": { title: "Automation", crumb: "Levers" },
  "/guardrails": { title: "Guardrails", crumb: "Quality" },
  "/guardrails/quality": { title: "Guardrails", crumb: "Quality" },
  "/guardrails/budgets": { title: "Guardrails", crumb: "Budgets" },
  "/guardrails/alerts": { title: "Guardrails", crumb: "Alerts" },
  "/proof": { title: "Savings", crumb: "Savings" },
  "/proof/savings": { title: "Savings", crumb: "Savings" },
  "/proof/attribution": { title: "Savings", crumb: "Attribution" },
  "/proof/data-quality": { title: "Savings", crumb: "Data Quality" },
  "/analysis": { title: "AI spend", crumb: "Spend" },
  "/analysis/spend": { title: "AI spend", crumb: "Spend" },
  "/analysis/customers": { title: "AI spend", crumb: "Customers" },
  "/analysis/models": { title: "AI spend", crumb: "Models" },
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
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
      <path d="M4 5h16M4 12h16M4 19h16" />
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

function ChevronUpDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m7 15 5 5 5-5M7 9l5-5 5 5" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
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

function useMenuDismiss(
  open: boolean,
  ref: RefObject<HTMLDivElement | null>,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  useEffect(() => {
    if (!open) return;

    const closeIfOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && ref.current?.contains(target)) return;
      setOpen(false);
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("pointerdown", closeIfOutside, true);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside, true);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, ref, setOpen]);
}

function ProjectSelector({
  activeProjectId,
  activeOrgId,
  getToken,
  navOpen,
  projects,
  projectName,
  refreshProjects,
  setActiveProjectId,
}: {
  activeProjectId: string | null;
  activeOrgId: string | null;
  getToken: () => Promise<string>;
  navOpen: boolean;
  projects: Project[];
  projectName: string;
  refreshProjects: () => Promise<void>;
  setActiveProjectId: (id: string) => void;
}) {
  const router = useRouter();
  const [projectOpen, setProjectOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const projectRef = useRef<HTMLDivElement | null>(null);
  useMenuDismiss(projectOpen, projectRef, setProjectOpen);

  const openCreate = () => {
    setProjectOpen(false);
    setCreateError(null);
    setCreateOpen(true);
  };

  const closeCreate = () => {
    if (createBusy) return;
    setCreateOpen(false);
    setCreateError(null);
  };

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = createName.trim();
    if (!name) return;
    if (!activeOrgId) {
      setCreateError("No organization is available for this project.");
      return;
    }

    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await api.createProject(await getToken(), activeOrgId, name);
      setActiveProjectId(created.id);
      await refreshProjects();
      setCreateName("");
      setCreateOpen(false);
      router.push("/admin/connections");
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreateBusy(false);
    }
  };

  return (
    <div className="lv-project-selector" ref={projectRef}>
      <button
        className="lv-project-button"
        type="button"
        aria-haspopup="menu"
        aria-expanded={projectOpen}
        aria-label={`Project: ${projectName}`}
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setProjectOpen((open) => !open)}
      >
        <span className="lv-project-avatar">{initials(projectName)}</span>
        <span className="lv-project-name">{projectName}</span>
        <span className="lv-project-chevron">
          <ChevronUpDownIcon />
        </span>
      </button>
      {projectOpen ? (
        <ProjectMenu
          activeProjectId={activeProjectId}
          onCreateProject={openCreate}
          onClose={() => setProjectOpen(false)}
          projects={projects}
          setActiveProjectId={setActiveProjectId}
        />
      ) : null}
      {createOpen ? (
        <CreateProjectModal
          busy={createBusy}
          error={createError}
          name={createName}
          onClose={closeCreate}
          onNameChange={setCreateName}
          onSubmit={submitCreate}
        />
      ) : null}
    </div>
  );
}

function ProjectMenu({
  activeProjectId,
  onCreateProject,
  onClose,
  projects,
  setActiveProjectId,
}: {
  activeProjectId: string | null;
  onCreateProject: () => void;
  onClose: () => void;
  projects: Project[];
  setActiveProjectId: (id: string) => void;
}) {
  const selectedProjectId = activeProjectId ?? projects[0]?.id ?? null;
  const selectProject = (project: Project) => {
    if (project.id !== activeProjectId) setActiveProjectId(project.id);
    onClose();
  };

  return (
    <div className="lv-project-menu" role="menu">
      <div className="lv-project-list" role="group" aria-label="Projects">
        {projects.length > 0 ? (
          projects.map((project) => {
            const active = project.id === selectedProjectId;
            return (
              <button
                key={project.id}
                className={`lv-project-menu-item${active ? " active" : ""}`}
                type="button"
                role="menuitem"
                aria-current={active ? "true" : undefined}
                onClick={() => selectProject(project)}
              >
                <span>{project.name}</span>
                {active ? (
                  <span className="lv-project-check">
                    <CheckIcon />
                  </span>
                ) : null}
              </button>
            );
          })
        ) : (
          <div className="lv-project-empty">No projects yet</div>
        )}
      </div>
      <div className="lv-project-menu-divider" role="separator" />
      <button className="lv-project-menu-item create" type="button" role="menuitem" onClick={onCreateProject}>
        <span>Create project</span>
        <span className="lv-project-plus">
          <PlusIcon />
        </span>
      </button>
    </div>
  );
}

function CreateProjectModal({
  busy,
  error,
  name,
  onClose,
  onNameChange,
  onSubmit,
}: {
  busy: boolean;
  error: string | null;
  name: string;
  onClose: () => void;
  onNameChange: (name: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="lv-project-modal-backdrop" role="presentation" onClick={onClose}>
      <form className="lv-project-modal" role="dialog" aria-modal="true" aria-labelledby="create-project-title" onClick={(event) => event.stopPropagation()} onSubmit={onSubmit}>
        <div className="lv-project-modal-head">
          <h2 id="create-project-title">Create project</h2>
        </div>
        <label className="lv-project-field">
          <span>Project name</span>
          <input
            autoFocus
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="Production"
            disabled={busy}
          />
        </label>
        {error ? <div className="lv-project-error">{error}</div> : null}
        <div className="lv-project-modal-actions">
          <button type="button" className="lv-project-secondary" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="lv-project-primary" disabled={busy || !name.trim()}>
            {busy ? "Creating..." : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
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
  useMenuDismiss(accountOpen, accountRef, setAccountOpen);

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

const ACCOUNT_MENU_ICONS = {
  profile: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  docs: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M9 13h6 M9 17h6 M9 9h1",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M9.1 9a2.9 2.9 0 1 1 3.8 2.8c-.9.4-1.4 1-1.4 2.2 M12 17h.01",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9",
} as const;

const THEME_OPTIONS = [
  {
    key: "light",
    label: "Light",
    icon: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M12 3v1.5 M12 19.5V21 M4.6 4.6l1.1 1.1 M18.3 18.3l1.1 1.1 M3 12h1.5 M19.5 12H21 M4.6 19.4l1.1-1.1 M18.3 5.7l1.1-1.1",
  },
  { key: "dark", label: "Dark", icon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" },
  { key: "system", label: "System", icon: "M3 4h18v12H3z M9 20h6 M12 16v4" },
] as const;

function ThemeToggle() {
  const [value, setValue] = useState<(typeof THEME_OPTIONS)[number]["key"]>("system");
  return (
    <div className="lv-account-theme" role="group" aria-label="Theme">
      {THEME_OPTIONS.map((option) => (
        <button
          key={option.key}
          type="button"
          className={value === option.key ? "active" : undefined}
          aria-pressed={value === option.key}
          aria-label={option.label}
          title={option.label}
          onClick={() => setValue(option.key)}
        >
          <Icon path={option.icon} />
        </button>
      ))}
    </div>
  );
}

function StaticMenuItem({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="lv-account-menu-item static" role="menuitem" aria-disabled="true">
      <span>{label}</span>
      <span className="lv-account-menu-soon pill neutral">Soon</span>
      <Icon path={icon} />
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
      <StaticMenuItem icon={ACCOUNT_MENU_ICONS.profile} label="Profile" />

      <div className="lv-account-menu-divider" role="separator" />

      <div className="lv-account-menu-item theme-row" role="group" aria-label="Theme">
        <span>Theme</span>
        <ThemeToggle />
      </div>

      <StaticMenuItem icon={ACCOUNT_MENU_ICONS.activity} label="Activity" />
      <StaticMenuItem icon={ACCOUNT_MENU_ICONS.docs} label="Docs" />
      <StaticMenuItem icon={ACCOUNT_MENU_ICONS.help} label="Help" />

      <div className="lv-account-menu-divider" role="separator" />

      <a href="/auth/logout" className="lv-account-menu-item" role="menuitem">
        <span>Log out</span>
        <Icon path={ACCOUNT_MENU_ICONS.logout} />
      </a>

      {plan.show && !isPerformance ? (
        <>
          <div className="lv-account-menu-divider" role="separator" />
          <Link
            href={plan.actionHref}
            className="lv-account-menu-item upgrade"
            role="menuitem"
            onClick={onClose}
          >
            {plan.actionLabel}
          </Link>
        </>
      ) : null}
    </div>
  );
}

function Sidebar({
  accountOpen,
  activeProjectId,
  activeOrgId,
  displayName,
  getToken,
  isLoading,
  navOpen,
  pathname,
  projectName,
  projects,
  refreshProjects,
  setActiveProjectId,
  setAccountOpen,
  userReady,
}: {
  accountOpen: boolean;
  activeProjectId: string | null;
  activeOrgId: string | null;
  displayName: string;
  getToken: () => Promise<string>;
  isLoading: boolean;
  navOpen: boolean;
  pathname: string;
  projectName: string;
  projects: Project[];
  refreshProjects: () => Promise<void>;
  setActiveProjectId: (id: string) => void;
  setAccountOpen: Dispatch<SetStateAction<boolean>>;
  userReady: boolean;
}) {
  return (
    <aside className="lv-sidebar" aria-label="Primary" aria-hidden={!navOpen}>
      <div className="lv-sidebar-inner">
        <div className="lv-brand">
          <ProjectSelector
            activeProjectId={activeProjectId}
            activeOrgId={activeOrgId}
            getToken={getToken}
            navOpen={navOpen}
            projectName={projectName}
            projects={projects}
            refreshProjects={refreshProjects}
            setActiveProjectId={setActiveProjectId}
          />
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

function activeOrgId(profile: UserProfile | null, project: Project | null): string | null {
  if (project?.organization_id) return project.organization_id;
  const organizations = profile?.organizations || [];
  return organizations[0]?.id || null;
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
  const { activeProjectId, getToken, profile, projects, refreshProjects, setActiveProjectId } = useSession();
  const [accountOpen, setAccountOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(!initialCollapsed);
  const hasMounted = useRef(false);
  const currentRoute = routeLabel(pathname);
  const activeProject = activeProjectFor(projects, activeProjectId);
  const orgId = activeOrgId(profile, activeProject);
  const { displayName, projectName } = shellNames({
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
          activeProjectId={activeProjectId}
          activeOrgId={orgId}
          displayName={displayName}
          getToken={getToken}
          isLoading={isLoading}
          navOpen={navOpen}
          pathname={pathname}
          projectName={projectName}
          projects={projects}
          refreshProjects={refreshProjects}
          setActiveProjectId={setActiveProjectId}
          setAccountOpen={setAccountOpen}
          userReady={!!user}
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
