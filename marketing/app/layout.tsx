import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { AnalyticsProvider } from "@/components/varsten/analytics/AnalyticsProvider";
import { SITE_URL } from "./site-links";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const jetbrainsMono = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Varsten — Measure and reduce AI spend",
  description:
    "A drop-in AI proxy that caches exact hits, routes traffic to the most cost-effective models, and proves quality with concurrent holdback evals.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "Varsten — Measure and reduce AI spend",
    description:
      "A drop-in AI proxy that caches exact hits, routes traffic to the most cost-effective models, and proves quality with concurrent holdback evals.",
    url: "/",
    siteName: "Varsten",
    type: "website",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Varsten" }],
  },
  icons: {
    icon: [{ url: "/varsten-icon.svg", type: "image/svg+xml" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#fbf9f3",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body>
        <AnalyticsProvider>{children}</AnalyticsProvider>
      </body>
    </html>
  );
}
