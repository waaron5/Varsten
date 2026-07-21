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
  align?: "start" | "end" | "stretch";
  mediaClassName?: string;
  eyebrowInGrid?: boolean;
};

type SectionProps = {
  id?: string;
  eyebrow?: string;
  title: string;
  description?: string;
  children: ReactNode;
  tone?: "default" | "muted" | "dark";
};
type SectionTone = NonNullable<SectionProps["tone"]>;

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

export function SecondaryHero({
  eyebrow,
  title,
  description,
  children,
  align = "end",
  mediaClassName = "border border-border bg-muted p-5",
  eyebrowInGrid = false,
}: HeroProps) {
  const eyebrowEl = <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">{eyebrow}</p>;

  return (
    <section className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1400px] px-6 py-18 md:px-10 md:py-24">
        <HeroEyebrowSlot eyebrow={eyebrowEl} show={!eyebrowInGrid} />
        <div
          className={`${heroGridOffset(eyebrowInGrid)} grid gap-8 md:grid-cols-[minmax(0,0.92fr)_minmax(320px,0.48fr)] ${heroAlignClass(align)}`}
        >
          <div>
            <HeroEyebrowSlot eyebrow={eyebrowEl} show={eyebrowInGrid} />
            <h1 className={`${heroTitleOffset(eyebrowInGrid)} max-w-4xl text-[44px] font-semibold leading-[1.02] tracking-[-0.02em] text-ink md:text-[72px]`}>
              {title}
            </h1>
            <p className="mt-6 max-w-2xl text-[17px] leading-8 text-ink-soft md:text-[19px]">{description}</p>
          </div>
          <HeroMedia className={mediaClassName}>{children}</HeroMedia>
        </div>
      </div>
    </section>
  );
}

function HeroEyebrowSlot({ eyebrow, show }: { eyebrow: ReactNode; show: boolean }) {
  return show ? eyebrow : null;
}

function HeroMedia({ children, className }: { children?: ReactNode; className: string }) {
  return children ? <div className={className}>{children}</div> : null;
}

function heroGridOffset(eyebrowInGrid: boolean): string {
  return eyebrowInGrid ? "" : "mt-6";
}

function heroTitleOffset(eyebrowInGrid: boolean): string {
  return eyebrowInGrid ? "mt-6" : "";
}

function heroAlignClass(align: NonNullable<HeroProps["align"]>): string {
  const classes: Record<NonNullable<HeroProps["align"]>, string> = {
    start: "md:items-start",
    stretch: "md:items-stretch",
    end: "md:items-end",
  };
  return classes[align];
}

function sectionToneClass(tone: SectionTone): string {
  const classes: Record<SectionTone, string> = {
    dark: "bg-ink text-primary-foreground",
    muted: "bg-muted text-ink",
    default: "bg-background text-ink",
  };
  return classes[tone];
}

function sectionEyebrowClass(tone: SectionTone): string {
  return tone === "dark" ? "text-white/55" : "text-ink-soft";
}

function sectionDescriptionClass(tone: SectionTone): string {
  return tone === "dark" ? "text-white/65" : "text-ink-soft";
}

export function SecondarySection({ id, eyebrow, title, description, children, tone = "default" }: SectionProps) {
  return (
    <section id={id} className={`border-b border-border ${sectionToneClass(tone)}`}>
      <div className="mx-auto max-w-[1400px] px-6 py-14 md:px-10 md:py-20">
        <div className="mb-10 max-w-3xl">
          {eyebrow ? (
            <p className={`mono text-[11px] uppercase tracking-[0.28em] ${sectionEyebrowClass(tone)}`}>
              {eyebrow}
            </p>
          ) : null}
          <h2 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]">
            {title}
          </h2>
          {description ? (
            <p className={`mt-4 text-[16px] leading-7 ${sectionDescriptionClass(tone)}`}>
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
  const columnClass = cardGridColumnClass(columns);
  return <div className={`grid grid-cols-1 gap-px border border-border bg-border ${columnClass}`}>{children}</div>;
}

function cardGridColumnClass(columns: 2 | 3 | 4): string {
  const classes = {
    2: "md:grid-cols-2",
    3: "md:grid-cols-3",
    4: "lg:grid-cols-4",
  };
  return classes[columns];
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
  intent: "trial" | "observe" | "early-access" | "sales";
}) {
  const event = pageCtaEvent(intent);

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

function pageCtaEvent(intent: "trial" | "observe" | "early-access" | "sales") {
  const events = {
    trial: "trial intent started",
    observe: "free audit started",
    "early-access": "early access intent started",
    sales: "sales intent started",
  } as const;
  return events[intent];
}
