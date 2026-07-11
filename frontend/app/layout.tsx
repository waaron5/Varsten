import type { Metadata } from "next";
import type { ComponentProps } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { Auth0Provider } from "@auth0/nextjs-auth0";
import { QueryProvider } from "@/components/queryProvider";
import { EntitlementsProvider } from "@/components/entitlements";
import { SessionProvider } from "@/components/session";
import { AppShell, SIDEBAR_COOKIE } from "@/components/AppShell";
import { auth0 } from "@/lib/auth0";
import { loadServerBootstrap } from "@/lib/serverSession";
import type { Project } from "@/lib/types";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const E2E_USER = {
  sub: "auth0|maya-enterprise",
  email: "maya@enterprise.example",
  name: "Maya Chen",
};

export const metadata: Metadata = {
  title: "Varsten — AI Savings Automation",
  description: "Cut AI spend safely and prove the savings.",
  icons: {
    icon: [{ url: "/varsten-icon.svg", type: "image/svg+xml" }],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { bootstrap, e2eUser, sessionUser, sidebarCollapsed } = await loadLayoutState();
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <RootProviders
          activeProjectId={bootstrap?.activeProjectId ?? null}
          e2eUser={e2eUser}
          projects={bootstrap?.projects}
          sessionUser={sessionUser}
          sidebarCollapsed={sidebarCollapsed}
        >
          {children}
        </RootProviders>
      </body>
    </html>
  );
}

async function loadLayoutState() {
  const cookieStore = await cookies();
  // Read the persisted sidebar state on the server so the shell renders with the
  // correct collapsed class on first paint. The client seeds its useState from the
  // same value, so server and client agree and there is no hydration mismatch.
  const sidebarCookie = cookieStore.get(SIDEBAR_COOKIE)?.value;
  const sidebarCollapsed = sidebarCookie === "collapsed" || sidebarCookie === "closed";
  const e2eUser = e2eAuthBypassEnabled(cookieStore.get("varsten_e2e_auth")?.value) ? E2E_USER : null;
  const session = e2eUser ? null : await auth0.getSession();
  // Resolve projects + active project on the server so the client can skip its
  // sync/projects bootstrap waterfall and the first paint is immediately "ready".
  const bootstrap = e2eUser ? null : await loadServerBootstrap();
  return { bootstrap, e2eUser, sessionUser: session?.user, sidebarCollapsed };
}

function RootProviders({
  activeProjectId,
  children,
  e2eUser,
  projects,
  sessionUser,
  sidebarCollapsed,
}: {
  activeProjectId: string | null;
  children: React.ReactNode;
  e2eUser: typeof E2E_USER | null;
  projects: Project[] | undefined;
  sessionUser: ComponentProps<typeof Auth0Provider>["user"];
  sidebarCollapsed: boolean;
}) {
  return (
    <Auth0Provider user={e2eUser ?? sessionUser}>
      <QueryProvider>
        <SessionProvider initialProjects={projects} initialActiveProjectId={activeProjectId}>
          <EntitlementsProvider>
            <AppShell initialCollapsed={sidebarCollapsed}>{children}</AppShell>
          </EntitlementsProvider>
        </SessionProvider>
      </QueryProvider>
    </Auth0Provider>
  );
}

function e2eAuthBypassEnabled(cookieValue: string | undefined): boolean {
  if (process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1") return true;
  return process.env.NODE_ENV === "development" && cookieValue === "1";
}
