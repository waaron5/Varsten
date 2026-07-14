import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MarkdownContent } from "@/components/varsten/MarkdownContent";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { StructuredData } from "@/components/varsten/StructuredData";
import { getAllDocs, getDoc } from "@/lib/content/docs";
import { breadcrumbList, pageMetadata } from "@/lib/seo";

export function generateStaticParams() {
  return getAllDocs().map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) {
    return pageMetadata({
      title: "Docs — Varsten",
      description: "Varsten technical documentation.",
      path: "/docs/quickstart",
    });
  }

  return pageMetadata({
    title: `${doc.title} — Varsten Docs`,
    description: doc.description,
    path: `/docs/${doc.slug}`,
  });
}

export default async function DocDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) notFound();

  const allDocs = getAllDocs();

  return (
    <SecondaryShell>
      <StructuredData
        data={breadcrumbList([
          { name: "Home", path: "/" },
          { name: "Docs", path: "/docs/quickstart" },
          { name: doc.title, path: `/docs/${doc.slug}` },
        ])}
      />
      <article className="border-b border-border bg-background">
        <div className="mx-auto grid max-w-[1400px] gap-10 px-6 py-12 md:grid-cols-[260px_minmax(0,1fr)] md:px-10 md:py-16">
          <aside className="md:sticky md:top-20 md:self-start">
            <nav className="grid border border-border bg-muted" aria-label="Docs">
              {allDocs.map((entry) => (
                <Link
                  key={entry.slug}
                  href={`/docs/${entry.slug}`}
                  className={`border-b border-border px-3 py-2.5 text-[13px] last:border-b-0 ${
                    entry.slug === doc.slug
                      ? "bg-border font-medium text-ink"
                      : "text-ink-soft hover:bg-secondary hover:text-ink"
                  }`}
                >
                  {entry.title}
                </Link>
              ))}
            </nav>
          </aside>

          <div>
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">
              {doc.category} · Updated {doc.updatedAt}
            </p>
            <h1 className="mt-5 max-w-3xl text-[42px] font-semibold leading-[1.05] tracking-[-0.02em] text-ink md:text-[64px]">
              {doc.title}
            </h1>
            <p className="mt-5 max-w-3xl text-[18px] leading-8 text-ink-soft">{doc.description}</p>
            <MarkdownContent markdown={doc.body} docSlug={doc.slug} />
          </div>
        </div>
      </article>
    </SecondaryShell>
  );
}
