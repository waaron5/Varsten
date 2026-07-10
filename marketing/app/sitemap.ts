import type { MetadataRoute } from "next";
import { SITE_URL, siteUrl } from "./site-links";
import { getAllDocs } from "@/lib/content/docs";

const staticRoutes = [
  "",
  "/pricing",
  "/proof",
  "/enterprise",
  "/faq",
  "/docs",
  "/security",
  "/about",
  "/contact",
  "/changelog",
  "/privacy",
  "/terms",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const staticEntries = staticRoutes.map((route) => ({
    url: siteUrl(route || "/"),
    lastModified: now,
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : route === "/docs" ? 0.9 : 0.7,
  })) satisfies MetadataRoute.Sitemap;

  const docEntries = getAllDocs().map((doc) => ({
    url: siteUrl(`/docs/${doc.slug}`),
    lastModified: new Date(doc.updatedAt),
    changeFrequency: "monthly",
    priority: 0.75,
  })) satisfies MetadataRoute.Sitemap;

  return [...staticEntries, ...docEntries];
}

export const dynamic = "force-static";
export const revalidate = 86_400;

export const metadataBase = new URL(SITE_URL);
