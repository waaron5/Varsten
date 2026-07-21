import type { ReactNode } from "react";

export type PolicySection = {
  id: string;
  title: string;
  content: ReactNode;
};

export function PolicyDocument({
  description,
  sections,
  title,
  updated,
}: {
  description: string;
  sections: PolicySection[];
  title: string;
  updated: string;
}) {
  return (
    <>
      <section className="border-b border-border bg-background">
        <div className="mx-auto max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">{title}</h1>
          <p className="mt-7 max-w-3xl text-[17px] leading-8 text-ink-soft">{description}</p>
          <p className="mono mt-7 text-[10px] uppercase tracking-[0.24em] text-ink-soft">Last updated {updated}</p>
        </div>
      </section>

      <section className="border-b border-border bg-background">
        <div className="mx-auto grid max-w-[1400px] gap-14 px-6 py-16 md:px-10 md:py-24 lg:grid-cols-[220px_minmax(0,760px)] lg:gap-24">
          <aside className="lg:sticky lg:top-24 lg:self-start">
            <p className="mono mb-5 text-[10px] uppercase tracking-[0.24em] text-ink-soft">Contents</p>
            <nav className="grid gap-3" aria-label={`${title} contents`}>
              {sections.map((section, index) => (
                <a key={section.id} href={`#${section.id}`} className="text-[12px] leading-5 text-ink-soft transition-colors hover:text-ink">
                  {String(index + 1).padStart(2, "0")} · {section.title}
                </a>
              ))}
            </nav>
          </aside>

          <div>
            {sections.map((section, index) => (
              <section key={section.id} id={section.id} className="scroll-mt-24 border-t border-border py-10 first:border-t-0 first:pt-0">
                <p className="mono text-[10px] uppercase tracking-[0.24em] text-ink-soft">{String(index + 1).padStart(2, "0")}</p>
                <h2 className="mt-3 text-[26px] font-semibold tracking-[-0.015em] text-ink md:text-[32px]">{section.title}</h2>
                <div className="policy-copy mt-5 grid gap-4 text-[15px] leading-7 text-ink-soft">{section.content}</div>
              </section>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

export function PolicyList({ children }: { children: ReactNode }) {
  return <ul className="grid list-disc gap-2 pl-5">{children}</ul>;
}
