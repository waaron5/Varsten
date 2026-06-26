import type { Metadata } from "next";
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

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Varsten — AI Savings Engine",
  description: "Cut AI spend safely and prove the savings.",
  icons: {
    icon: [{ url: "/varsten-icon.svg", type: "image/svg+xml" }],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  // Read the persisted sidebar state on the server so the shell renders with the
  // correct collapsed class on first paint. The client seeds its useState from the
  // same value, so server and client agree and there is no hydration mismatch.
  const sidebarCollapsed = cookieStore.get(SIDEBAR_COOKIE)?.value === "collapsed";
  const e2eUser = (
    process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1" ||
    (process.env.NODE_ENV === "development" && cookieStore.get("varsten_e2e_auth")?.value === "1")
  )
    ? {
        sub: "auth0|maya-enterprise",
        email: "maya@enterprise.example",
        name: "Maya Chen",
      }
    : null;
  const session = e2eUser ? null : await auth0.getSession();
  // Resolve projects + active project on the server so the client can skip its
  // sync/projects bootstrap waterfall and the first paint is immediately "ready".
  const bootstrap = e2eUser ? null : await loadServerBootstrap();
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <Auth0Provider user={e2eUser ?? session?.user}>
          <QueryProvider>
            <SessionProvider
              initialProjects={bootstrap?.projects}
              initialActiveProjectId={bootstrap?.activeProjectId ?? null}
            >
              <EntitlementsProvider>
                <AppShell initialCollapsed={sidebarCollapsed}>{children}</AppShell>
              </EntitlementsProvider>
            </SessionProvider>
          </QueryProvider>
        </Auth0Provider>
      </body>
    </html>
  );
}
