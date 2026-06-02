import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Auth0Provider } from "@auth0/nextjs-auth0";
import { ApiKeyProvider } from "@/components/providers";
import { SessionProvider } from "@/components/session";
import { AppShell } from "@/components/AppShell";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Varsten — AI Spend Intelligence",
  description: "Measure, track, and analyze AI spending across providers and models.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-theme="dark" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <Auth0Provider>
          <SessionProvider>
            <ApiKeyProvider>
              <AppShell>{children}</AppShell>
            </ApiKeyProvider>
          </SessionProvider>
        </Auth0Provider>
      </body>
    </html>
  );
}
