import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { NumberedList, SecondaryHero, SecondarySection, SecondaryShell } from "@/components/varsten/SecondaryPage";

export const metadata: Metadata = pageMetadata({
  title: "Changelog — Varsten",
  description: "Product updates and release notes for Varsten.",
  path: "/changelog",
});

export default function ChangelogPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Changelog"
        title="Product updates"
        description="Public release notes will live here as the marketing site, docs, and product surface move toward broader availability."
      />
      <SecondarySection title="Current public notes">
        <NumberedList
          items={[
            {
              title: "Landing architecture expanded",
              body: "Secondary buyer routes, docs SEO, sitemap, robots, and analytics instrumentation were added without changing the homepage design.",
            },
            {
              title: "Docs moved to markdown",
              body: "Developer docs now use validated frontmatter, dynamic metadata, canonical URLs, and Breadcrumb structured data.",
            },
          ]}
        />
      </SecondarySection>
    </SecondaryShell>
  );
}
