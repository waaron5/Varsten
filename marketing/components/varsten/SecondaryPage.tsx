import type { ReactNode } from "react";
import { Footer } from "./Footer";
import { Nav } from "./Nav";
import { TrackedLink } from "./TrackedLink";

type ShellProps = {
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

type PageCtaProps = {
  title: string;
  description?: string;
  href: string;
  label: string;
  intent: "trial" | "observe" | "early-access" | "sales";
  arrow?: boolean;
  hideEyebrow?: boolean;
};

function PageCtaEyebrow({ hidden }: { hidden: boolean }) {
  if (hidden) return null;
  return <p className="mono text-[11px] uppercase tracking-[0.28em] text-white/45">Next step</p>;
}

function PageCtaDescription({ children }: { children?: string }) {
  if (!children) return null;
  return <p className="mt-3 max-w-2xl text-[15px] leading-7 text-white/65">{children}</p>;
}

function PageCtaArrow({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <span className="ml-3" aria-hidden="true">→</span>;
}

export function PageCta({
  title,
  description,
  href,
  label,
  intent,
  arrow = true,
  hideEyebrow = false,
}: PageCtaProps) {
  const event = pageCtaEvent(intent);

  return (
    <section className="border-b border-border bg-ink text-primary-foreground">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-6 px-6 py-12 md:flex-row md:items-center md:justify-between md:px-10">
        <div>
          <PageCtaEyebrow hidden={hideEyebrow} />
          <h2 className={`${hideEyebrow ? "" : "mt-3"} max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.01em] md:text-[44px]`}>
            {title}
          </h2>
          <PageCtaDescription>{description}</PageCtaDescription>
        </div>
        <TrackedLink
          href={href}
          event={event}
          eventProperties={{ cta: label, intent }}
          className="inline-flex h-11 shrink-0 items-center justify-center bg-background px-4 text-[13px] font-medium text-ink transition-opacity hover:opacity-90"
        >
          {label}<PageCtaArrow visible={arrow} />
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
