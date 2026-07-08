import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import "./content.css";
import { APP_URL, CONTACT_EMAIL, DPA_REQUEST_HREF, START_FREE_HREF } from "./site-links";

function Logo({ variant = "dark" }: { variant?: "dark" | "light" }) {
  return (
    <Image
      className="lp-logo-img"
      src={variant === "light" ? "/varsten-logo.svg" : "/varsten-logo-black.svg"}
      width={458}
      height={93}
      alt=""
      aria-hidden="true"
    />
  );
}

type ContentPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
};

type ContentSectionProps = {
  id?: string;
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

export function ContentSection({ id, eyebrow, title, children }: ContentSectionProps) {
  return (
    <section id={id} className="lp-content-section">
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
    <header className="lp-nav scrolled">
      <div className="lp-container lp-nav-inner">
        <Link className="lp-logo" href="/" aria-label="Varsten home">
          <Logo />
        </Link>
        <nav className="lp-nav-center" aria-label="Primary">
          <Link href="/#levers">Levers</Link>
          <Link href="/#integrations">Integrations</Link>
          <Link href="/#pricing">Pricing</Link>
          <Link href="/docs">Docs</Link>
        </nav>
        <div className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>
            Sign in
          </a>
          <Link className="lp-btn lp-btn-primary" href={START_FREE_HREF}>
            Start free
          </Link>
        </div>
      </div>
    </header>
  );
}

function ContentFooter() {
  return (
    <footer className="lp-footer on-dark">
      <div className="lp-container">
        <div className="lp-footer-grid">
          <div className="lp-footer-brand">
            <Link className="lp-logo" href="/" aria-label="Varsten home">
              <Logo variant="light" />
            </Link>
            <p>Cut AI spend without losing quality. An inline proxy that shows you what it saved.</p>
          </div>
          <div className="lp-footer-col">
            <h4>Product</h4>
            <Link href="/#top">Overview</Link>
            <Link href="/#levers">Savings levers</Link>
            <Link href="/#integrations">Integrations</Link>
            <Link href="/#pricing">Pricing</Link>
          </div>
          <div className="lp-footer-col">
            <h4>Company</h4>
            <Link href="/docs">Docs</Link>
            <Link href="/status">Status</Link>
            <Link href="/contact">Contact</Link>
          </div>
          <div className="lp-footer-col">
            <h4>Legal</h4>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/security">Security</Link>
            <a href={DPA_REQUEST_HREF}>DPA</a>
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
