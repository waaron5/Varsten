import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { APP_URL, CONTACT_EMAIL, CONTACT_HREF, DPA_REQUEST_HREF, START_FREE_HREF } from "./site-links";

type ContentPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
};

type ContentSectionProps = {
  eyebrow?: string;
  title: string;
  children: ReactNode;
};

export function ContentPage({ eyebrow, title, description, children }: ContentPageProps) {
  return (
    <main className="lp-page lp-content-page">
      <ContentNav />
      <section className="lp-content-hero">
        <div className="lp-container">
          <p className="lp-eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </section>
      <div className="lp-content-body">
        <div className="lp-container">{children}</div>
      </div>
      <ContentFooter />
    </main>
  );
}

export function ContentSection({ eyebrow, title, children }: ContentSectionProps) {
  return (
    <section className="lp-content-section">
      {eyebrow ? <p className="lp-eyebrow muted">{eyebrow}</p> : null}
      <h2>{title}</h2>
      <div className="lp-content-section-body">{children}</div>
    </section>
  );
}

export function ContentGrid({ children }: { children: ReactNode }) {
  return <div className="lp-content-grid">{children}</div>;
}

export function ContentCard({ title, children }: ContentSectionProps) {
  return (
    <article className="lp-content-card">
      <h3>{title}</h3>
      {children}
    </article>
  );
}

export function ContentCallout({ title, children }: ContentSectionProps) {
  return (
    <aside className="lp-content-callout">
      <h3>{title}</h3>
      {children}
    </aside>
  );
}

export function ContentCode({ children }: { children: ReactNode }) {
  return (
    <pre className="lp-content-code">
      <code>{children}</code>
    </pre>
  );
}

function ContentNav() {
  return (
    <header className="lp-content-nav">
      <div className="lp-container lp-content-nav-inner">
        <Link className="lp-logo" href="/" aria-label="Varsten home">
          <Image src="/varsten-logo.svg" alt="Varsten" width={180} height={37} priority />
        </Link>
        <nav className="lp-content-nav-center" aria-label="Primary">
          <Link href="/#how-it-works">Product</Link>
          <Link href="/#pricing">Pricing</Link>
          <Link href="/docs">Docs</Link>
          <Link href="/security">Security</Link>
        </nav>
        <div className="lp-content-nav-right">
          <a className="lp-link" href={APP_URL}>
            Sign in
          </a>
          <Link className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" href={START_FREE_HREF}>
            Start Free
          </Link>
        </div>
      </div>
    </header>
  );
}

function ContentFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-wrap">
        <div className="lp-footer-grid">
          <div className="lp-footer-brand">
            <div className="lp-footer-logo" aria-label="Varsten">
              <Image src="/varsten-logo.svg" alt="Varsten" width={176} height={36} />
            </div>
            <p>Reduce AI spend without sacrificing quality. The proxy that proves its savings.</p>
            <Link className="lp-btn lp-btn-primary lp-btn-cta" href={START_FREE_HREF}>
              Start Free
            </Link>
          </div>
          <div>
            <h4>Product</h4>
            <Link href="/#how-it-works">Drop-in Proxy</Link>
            <Link href="/#response-reuse">Response Reuse</Link>
            <Link href="/#routing-evals">Routing & Evals</Link>
            <Link href="/#savings-proof">Savings Proof</Link>
            <Link href="/#pricing">Pricing</Link>
          </div>
          <div>
            <h4>Company</h4>
            <a href={CONTACT_HREF}>Contact</a>
            <Link href="/docs">Docs</Link>
          </div>
          <div>
            <h4>Legal</h4>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/security">Security</Link>
            <a href={DPA_REQUEST_HREF}>Request DPA</a>
          </div>
        </div>
        <div className="lp-footer-bottom">
          <span>&copy; 2026 Varsten, Inc. All rights reserved.</span>
        </div>
      </div>
    </footer>
  );
}

export { CONTACT_EMAIL };
