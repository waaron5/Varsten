import type { Metadata } from "next";
import Link from "next/link";
import { getDocsByCategory } from "@/lib/content/docs";
import { breadcrumbList, pageMetadata } from "@/lib/seo";
import { StructuredData } from "@/components/varsten/StructuredData";
import {
  CardGrid,
  InfoCard,
  SecondaryHero,
  SecondarySection,
  SecondaryShell,
} from "@/components/varsten/SecondaryPage";

export const metadata: Metadata = pageMetadata({
  title: "Docs — Varsten",
  description:
    "Technical setup guides for integrating Varsten with OpenAI workloads, metadata-only analysis, fail-open behavior, and savings proof.",
  path: "/docs",
});

export default function DocsPage() {
  const docsByCategory = getDocsByCategory();

  return (
    <SecondaryShell>
      <StructuredData data={breadcrumbList([{ name: "Home", path: "/" }, { name: "Docs", path: "/docs" }])} />
      <SecondaryHero
        eyebrow="Docs"
        title="Build with Varsten without changing your AI product surface."
        description="Start with one workload, keep fallback explicit, and use metadata carefully. These docs cover the integration paths, provider boundaries, and proof model."
      />

      <SecondarySection
        title="Start here"
        description="The first pass should prove traffic, fallback, and attribution before broader optimization."
      >
        <CardGrid>
          {["quickstart", "openai-sdk", "fail-open-behavior"].map((slug) => {
            const doc = Object.values(docsByCategory)
              .flat()
              .find((entry) => entry.slug === slug);
            if (!doc) return null;
            return (
              <Link key={doc.slug} href={`/docs/${doc.slug}`} className="block bg-background p-6 transition-colors hover:bg-muted">
                <p className="mono text-[10px] uppercase tracking-[0.24em] text-blueprint">{doc.category}</p>
                <h2 className="mt-4 text-[22px] font-semibold tracking-[-0.01em] text-ink">{doc.title}</h2>
                <p className="mt-3 text-[14px] leading-6 text-ink-soft">{doc.description}</p>
              </Link>
            );
          })}
        </CardGrid>
      </SecondarySection>

      {Object.entries(docsByCategory).map(([category, docs]) => (
        <SecondarySection key={category} title={category} tone="muted">
          <CardGrid columns={2}>
            {docs.map((doc) => (
              <InfoCard key={doc.slug} eyebrow={doc.updatedAt} title={doc.title}>
                <p>{doc.description}</p>
                <Link
                  href={`/docs/${doc.slug}`}
                  className="mt-5 inline-flex text-[13px] font-medium text-blueprint underline underline-offset-4"
                >
                  Read guide
                </Link>
              </InfoCard>
            ))}
          </CardGrid>
        </SecondarySection>
      ))}
    </SecondaryShell>
  );
}
