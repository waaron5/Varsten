import Link from "next/link";
import { APP_URL, START_TRIAL_HREF } from "@/app/site-links";

export function Nav() {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-6 md:px-10">
        <a href="#top" className="flex items-center gap-2">
          <span className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">
            V—001
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-ink">
            Varsten
          </span>
        </a>
        <nav className="hidden items-center gap-8 md:flex">
          {[
            ["Levers", "#levers"],
            ["Integrations", "#integrations"],
            ["Pricing", "#pricing"],
            ["Docs", "/docs"],
          ].map(([label, href]) => (
            <a
              key={label}
              href={href}
              className="text-[13px] text-ink-soft transition-colors hover:text-ink"
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <a
            href={APP_URL}
            className="hidden text-[13px] text-ink-soft transition-colors hover:text-ink md:inline"
          >
            Sign in
          </a>
          <Link
            href={START_TRIAL_HREF}
            className="inline-flex h-8 items-center gap-2 bg-ink px-3 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Start free trial
            <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
