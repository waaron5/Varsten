import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { Auth0Provider } from "@auth0/nextjs-auth0";
import { ApiKeyProvider } from "@/components/providers";
import { SessionProvider } from "@/components/session";
import { AppShell, SIDEBAR_COOKIE } from "@/components/AppShell";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Varsten — AI Savings Engine",
  description: "Cut AI spend safely and prove the savings.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Read the persisted sidebar state on the server so the shell renders with the
  // correct collapsed class on first paint. The client seeds its useState from the
  // same value, so server and client agree and there is no hydration mismatch.
  const sidebarCollapsed = (await cookies()).get(SIDEBAR_COOKIE)?.value === "collapsed";
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <Auth0Provider>
          <SessionProvider>
            <ApiKeyProvider>
              <AppShell initialCollapsed={sidebarCollapsed}>{children}</AppShell>
            </ApiKeyProvider>
          </SessionProvider>
        </Auth0Provider>
      </body>
    </html>
  );
}
