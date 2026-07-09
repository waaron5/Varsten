import type { ReactNode } from "react";
import { Footer } from "./Footer";
import { Nav } from "./Nav";
import { TrackedLink } from "./TrackedLink";

type ShellProps = {
  children: ReactNode;
};

type HeroProps = {
  eyebrow: string;
  title: string;
  description: string;
  children?: ReactNode;
};

type SectionProps = {
  id?: string;
  eyebrow?: string;
  title: string;
  description?: string;
  children: ReactNode;
  tone?: "default" | "muted" | "dark";
};

type CardProps = {
  eyebrow?: string;
  title: string;
  children: ReactNode;
};

export function SecondaryShell({ children }: ShellProps) {
  return (
    <div className="min-h-screen bg-background text-ink">
      <Nav />
      <main>{children}</main>
      <Footer />
    </div>
  );
}

export function SecondaryHero({ eyebrow, title, description, children }: HeroProps) {
  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1400px] px-6 py-18 md:px-10 md:py-24">
        <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">{eyebrow}</p>
        <div className="mt-6 grid gap-8 md:grid-cols-[minmax(0,0.92fr)_minmax(320px,0.48fr)] md:items-end">
          <div>
            <h1 className="max-w-4xl text-[44px] font-semibold leading-[1.02] tracking-[-0.02em] text-ink md:text-[72px]">
              {title}
            </h1>
            <p className="mt-6 max-w-2xl text-[17px] leading-8 text-ink-soft md:text-[19px]">{description}</p>
          </div>
          {children ? <div className="border border-border bg-muted p-5">{children}</div> : null}
        </div>
      </div>
    </section>
  );
}

export function SecondarySection({ id, eyebrow, title, description, children, tone = "default" }: SectionProps) {
  const toneClass =
    tone === "dark"
      ? "bg-ink text-primary-foreground"
      : tone === "muted"
        ? "bg-muted text-ink"
        : "bg-background text-ink";

  return (
    <section id={id} className={`border-b border-border ${toneClass}`}>
      <div className="mx-auto max-w-[1400px] px-6 py-14 md:px-10 md:py-20">
        <div className="mb-10 max-w-3xl">
          {eyebrow ? (
            <p
              className={`mono text-[11px] uppercase tracking-[0.28em] ${
                tone === "dark" ? "text-white/55" : "text-ink-soft"
              }`}
            >
              {eyebrow}
            </p>
          ) : null}
          <h2 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]">
            {title}
          </h2>
          {description ? (
            <p className={`mt-4 text-[16px] leading-7 ${tone === "dark" ? "text-white/65" : "text-ink-soft"}`}>
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  );
}

export function CardGrid({ children, columns = 3 }: { children: ReactNode; columns?: 2 | 3 | 4 }) {
  const columnClass = columns === 4 ? "lg:grid-cols-4" : columns === 2 ? "md:grid-cols-2" : "md:grid-cols-3";
  return <div className={`grid grid-cols-1 gap-px border border-border bg-border ${columnClass}`}>{children}</div>;
}

export function InfoCard({ eyebrow, title, children }: CardProps) {
  return (
    <article className="min-h-[220px] bg-background p-6">
      {eyebrow ? <p className="mono text-[10px] uppercase tracking-[0.24em] text-blueprint">{eyebrow}</p> : null}
      <h3 className="mt-3 text-[20px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      <div className="mt-4 text-[14px] leading-6 text-ink-soft">{children}</div>
    </article>
  );
}

export function NumberedList({ items }: { items: { title: string; body: string }[] }) {
  return (
    <div className="grid gap-px border border-border bg-border">
      {items.map((item, index) => (
        <article key={item.title} className="grid gap-4 bg-background p-5 md:grid-cols-[80px_1fr] md:p-6">
          <div className="mono text-[13px] uppercase tracking-[0.24em] text-blueprint">
            {String(index + 1).padStart(2, "0")}
          </div>
          <div>
            <h3 className="text-[18px] font-semibold text-ink">{item.title}</h3>
            <p className="mt-2 max-w-3xl text-[14px] leading-6 text-ink-soft">{item.body}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

export function StatBand({ stats }: { stats: { label: string; value: string; detail: string }[] }) {
  return (
    <div className="grid border border-border bg-background md:grid-cols-3">
      {stats.map((stat) => (
        <div key={stat.label} className="border-b border-border p-6 last:border-b-0 md:border-b-0 md:border-r md:last:border-r-0">
          <p className="mono text-[10px] uppercase tracking-[0.24em] text-ink-soft">{stat.label}</p>
          <div className="mt-5 text-[38px] font-semibold tracking-[-0.02em] text-ink">{stat.value}</div>
          <p className="mt-2 text-[13px] leading-6 text-ink-soft">{stat.detail}</p>
        </div>
      ))}
    </div>
  );
}

export function PageCta({
  title,
  description,
  href,
  label,
  intent,
}: {
  title: string;
  description: string;
  href: string;
  label: string;
  intent: "trial" | "observe" | "sales";
}) {
  const event =
    intent === "trial" ? "trial intent started" : intent === "observe" ? "observe intent started" : "sales intent started";

  return (
    <section className="border-b border-border bg-ink text-primary-foreground">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-6 px-6 py-12 md:flex-row md:items-center md:justify-between md:px-10">
        <div>
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-white/45">Next step</p>
          <h2 className="mt-3 max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]">
            {title}
          </h2>
          <p className="mt-3 max-w-2xl text-[15px] leading-7 text-white/65">{description}</p>
        </div>
        <TrackedLink
          href={href}
          event={event}
          eventProperties={{ cta: label, intent }}
          className="inline-flex h-11 shrink-0 items-center justify-center bg-background px-4 text-[13px] font-medium text-ink transition-opacity hover:opacity-90"
        >
          {label}
        </TrackedLink>
      </div>
    </section>
  );
}
