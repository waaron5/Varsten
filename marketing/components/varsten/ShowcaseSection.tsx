import type { ReactNode } from "react";

type ShowcaseSectionProps = {
  eyebrow: string;
  title: string;
  description?: string;
  children: ReactNode;
};

function SectionDescription({ children }: { children?: string }) {
  if (!children) return null;
  return <p className="mt-5 text-[15px] leading-7 text-ink-soft">{children}</p>;
}

function SectionHeading({ eyebrow, title, description, wide }: { eyebrow: string; title: string; description?: string; wide: boolean }) {
  return (
    <div className={wide ? "max-w-xl" : "max-w-sm"}>
      <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">{eyebrow}</p>
      <h2 className="mt-4 text-[30px] font-semibold leading-[1.12] tracking-[-0.02em] md:text-[42px]">{title}</h2>
      <SectionDescription>{description}</SectionDescription>
    </div>
  );
}

export function SplitShowcaseSection({ eyebrow, title, description, children }: ShowcaseSectionProps) {
  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto grid max-w-[1400px] gap-12 px-6 py-24 md:px-10 md:py-36 lg:grid-cols-[minmax(220px,0.34fr)_minmax(0,1fr)] lg:gap-20">
        <SectionHeading eyebrow={eyebrow} title={title} description={description} wide={false} />
        {children}
      </div>
    </section>
  );
}

export function FullShowcaseSection({ eyebrow, title, children }: ShowcaseSectionProps) {
  return (
    <section className="border-b border-border bg-muted">
      <div className="mx-auto max-w-[1400px] px-6 py-24 md:px-10 md:py-36">
        <SectionHeading eyebrow={eyebrow} title={title} wide />
        {children}
      </div>
    </section>
  );
}
