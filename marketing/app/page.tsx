"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type MutableRefObject,
  type ReactNode,
  type RefObject,
} from "react";
import Image from "next/image";
import Link from "next/link";
import { APP_URL, CONTACT_HREF, DPA_REQUEST_HREF } from "./site-links";

const SAVINGS_RATE = 0.2;
const VARSTEN_SHARE = 0.25;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const metricCards = [
  { label: "Total spend", value: "$2,418", note: "34% saved", positive: true },
  { label: "Requests", value: "48.2K", note: "this month" },
  { label: "Cache rate", value: "61%", note: "8 pts", positive: true },
  { label: "Quality", value: "94.2", note: "no loss" },
];

const planFeatures = {
  free: [
    "Ongoing AI spend monitoring",
    "Month-by-month spend trends",
    "Savings recommendations by route, model, and workload",
    "Pricing and catalog trust checks",
    "Read-only Proof dashboard",
  ],
  performance: [
    "Everything in Free, plus:",
    "Automated routing, caching, batching, and model swaps",
    "Quality guardrails and active rollback",
    "Verified savings ledger",
    "You keep 75% of every verified dollar saved",
    "If Varsten saves $0, you pay $0",
  ],
};

const savingsRules = [
  "Cached repeat responses where the avoided model call cost is known.",
  "Batch routing measured as sync price minus batch price.",
  "Routing and model swaps measured against a live holdback or approved eval gate.",
  "Quality guardrails and rollback history attached to each optimization.",
  "Recommendations, estimates, and customer-side changes are not billed.",
];

function Check() {
  return (
    <svg
      className="lp-check"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function useEscapeClose(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
}

function ModalShell({
  children,
  labelledBy,
  onClose,
  wide,
}: {
  children: ReactNode;
  labelledBy: string;
  onClose: () => void;
  wide?: boolean;
}) {
  function handleOverlayClick(e: MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose();
  }

  return (
    <div
      className="lp-modal-overlay"
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
    >
      <div className={`lp-modal${wide ? " lp-modal-wide" : ""}`}>{children}</div>
    </div>
  );
}

function ModalHeader({
  eyebrow,
  title,
  subtitle,
  titleId,
  onClose,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  titleId: string;
  onClose: () => void;
}) {
  return (
    <div className="lp-modal-head">
      <div className="lp-modal-head-text">
        {eyebrow ? <p className="lp-eyebrow">{eyebrow}</p> : null}
        <p className="lp-modal-title" id={titleId}>
          {title}
        </p>
        {subtitle ? <p className="lp-modal-sub">{subtitle}</p> : null}
      </div>
      <button className="lp-modal-close" onClick={onClose} aria-label="Close">
        &#x2715;
      </button>
    </div>
  );
}

function EmailSuccess() {
  return (
    <div className="lp-modal-body">
      <div className="lp-modal-success">
        <div className="lp-modal-success-icon">
          <Check />
        </div>
        <p className="lp-modal-title">Request received.</p>
        <p>We do a secure, 15-minute white-glove setup to provision your tenant and keys. Check your inbox.</p>
      </div>
    </div>
  );
}

function EmailForm({
  email,
  error,
  fullName,
  companyName,
  inputRef,
  onCancel,
  onEmailChange,
  onFullNameChange,
  onCompanyNameChange,
  onSubmit,
  submitting,
}: {
  email: string;
  error: string | null;
  fullName: string;
  companyName: string;
  inputRef: RefObject<HTMLInputElement | null>;
  onCancel: () => void;
  onEmailChange: (email: string) => void;
  onFullNameChange: (name: string) => void;
  onCompanyNameChange: (company: string) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
}) {
  return (
    <form onSubmit={onSubmit}>
      <div className="lp-modal-body">
        <label className="lp-input-label" htmlFor="email-input">
          Work email
        </label>
        <input
          ref={inputRef}
          id="email-input"
          className="lp-input"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => onEmailChange(e.target.value)}
          required
          autoComplete="email"
        />
        <label className="lp-input-label" htmlFor="name-input">
          Full name
        </label>
        <input
          id="name-input"
          className="lp-input"
          type="text"
          placeholder="Jane Smith"
          value={fullName}
          onChange={(e) => onFullNameChange(e.target.value)}
          required
          autoComplete="name"
        />
        <label className="lp-input-label" htmlFor="company-input">
          Company name
        </label>
        <input
          id="company-input"
          className="lp-input"
          type="text"
          placeholder="Acme"
          value={companyName}
          onChange={(e) => onCompanyNameChange(e.target.value)}
          required
          autoComplete="organization"
        />
        {error ? (
          <p className="lp-form-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
      <div className="lp-modal-foot">
        <button type="button" className="lp-btn lp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="lp-btn lp-btn-primary"
          disabled={!email.trim() || !fullName.trim() || !companyName.trim() || submitting}
        >
          {submitting ? "Sending..." : "Confirm"}
        </button>
      </div>
    </form>
  );
}

function EmailModalHeader({ submitted, onClose }: { submitted: boolean; onClose: () => void }) {
  if (submitted) {
    return <ModalHeader title="You're on the list." titleId="email-modal-title" onClose={onClose} />;
  }

  return (
    <ModalHeader
      eyebrow="Get started"
      title="Enter your work email"
      subtitle="Someone from the team will reach out shortly to get you set up."
      titleId="email-modal-title"
      onClose={onClose}
    />
  );
}

function EmailModalContent({
  email,
  error,
  fullName,
  companyName,
  inputRef,
  submitted,
  submitting,
  onClose,
  onEmailChange,
  onFullNameChange,
  onCompanyNameChange,
  onSubmit,
}: {
  email: string;
  error: string | null;
  fullName: string;
  companyName: string;
  inputRef: RefObject<HTMLInputElement | null>;
  submitted: boolean;
  submitting: boolean;
  onClose: () => void;
  onEmailChange: (email: string) => void;
  onFullNameChange: (name: string) => void;
  onCompanyNameChange: (company: string) => void;
  onSubmit: (e: FormEvent) => void;
}) {
  if (submitted) {
    return (
      <>
        <EmailSuccess />
        <div className="lp-modal-foot">
          <button type="button" className="lp-btn lp-btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </>
    );
  }

  return (
    <EmailForm
      email={email}
      error={error}
      fullName={fullName}
      companyName={companyName}
      inputRef={inputRef}
      onCancel={onClose}
      onEmailChange={onEmailChange}
      onFullNameChange={onFullNameChange}
      onCompanyNameChange={onCompanyNameChange}
      onSubmit={onSubmit}
      submitting={submitting}
    />
  );
}

function EmailModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          fullName: fullName.trim(),
          companyName: companyName.trim(),
          source: "landing-cta",
        }),
      });
      if (!res.ok) {
        throw new Error(`request failed (${res.status})`);
      }
      setSubmitted(true);
    } catch {
      setError("Something went wrong sending your email. Please try again in a moment.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell labelledBy="email-modal-title" onClose={onClose}>
      <EmailModalHeader submitted={submitted} onClose={onClose} />
      <EmailModalContent
        email={email}
        error={error}
        fullName={fullName}
        companyName={companyName}
        inputRef={inputRef}
        submitted={submitted}
        submitting={submitting}
        onClose={onClose}
        onEmailChange={setEmail}
        onFullNameChange={setFullName}
        onCompanyNameChange={setCompanyName}
        onSubmit={handleSubmit}
      />
    </ModalShell>
  );
}

function DemoModal({ onClose }: { onClose: () => void }) {
  useEscapeClose(onClose);

  return (
    <ModalShell labelledBy="demo-modal-title" onClose={onClose} wide>
      <ModalHeader eyebrow="Product demo" title="See Varsten in action" titleId="demo-modal-title" onClose={onClose} />
      <div className="lp-modal-body">
        <div className="lp-demo-placeholder" aria-label="Demo video placeholder">
          <div className="lp-demo-play" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
          <span>Demo coming soon</span>
        </div>
      </div>
    </ModalShell>
  );
}

function Terrain({ variant }: { variant: "hero" | "proxy" | "feature" | "pricing" | "proof" | "footer" }) {
  return (
    <svg className={`lp-terrain lp-terrain-${variant}`} viewBox="0 0 1440 760" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <g className="lp-rings lp-rings-a">
        {[90, 178, 275, 382, 498, 624, 760, 906].map((rx, index) => (
          <ellipse
            key={rx}
            cx="1410"
            cy="-50"
            rx={rx}
            ry={Math.round(rx * 0.665)}
            transform="rotate(-20 1410 -50)"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6 - index * 0.14}
            opacity={0.21 - index * 0.027}
          />
        ))}
      </g>
      <g className="lp-rings lp-rings-b">
        {[155, 278, 412, 558, 730].map((rx, index) => (
          <ellipse
            key={rx}
            cx="-20"
            cy="760"
            rx={rx}
            ry={Math.round(rx * 0.665)}
            transform="rotate(13 -20 760)"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.1 - index * 0.12}
            opacity={0.1 - index * 0.018}
          />
        ))}
      </g>
      <g className="lp-tiles">
        <path d="M 1240,497 L 1370,562 L 1240,627 L 1110,562 Z" />
        <path d="M 1370,562 L 1240,627 L 1240,658 L 1370,593 Z" />
        <path d="M 1110,562 L 1240,627 L 1240,658 L 1110,593 Z" />
      </g>
      <g className="lp-tiles lp-tiles-small">
        <path d="M 1358,408 L 1440,449 L 1358,490 L 1276,449 Z" />
        <path d="M 1440,449 L 1358,490 L 1358,510 L 1440,469 Z" />
        <path d="M 1276,449 L 1358,490 L 1358,510 L 1276,469 Z" />
      </g>
    </svg>
  );
}

function hashTarget(hash: string): HTMLElement | null {
  if (!hash || hash === "#") return null;
  try {
    return document.getElementById(decodeURIComponent(hash.slice(1)));
  } catch {
    return null;
  }
}

function anchorScrollOffset(): number {
  const raw = window.getComputedStyle(document.documentElement).getPropertyValue("--anchor-scroll-offset");
  const offset = Number.parseFloat(raw);
  return Number.isFinite(offset) ? offset : 0;
}

function useSmoothHashLinks(): MutableRefObject<boolean> {
  const anchorScrollingRef = useRef(false);
  const finishTimerRef = useRef<number | null>(null);

  useEffect(() => {
    function finishAnchorScroll() {
      anchorScrollingRef.current = false;
      if (finishTimerRef.current !== null) {
        window.clearTimeout(finishTimerRef.current);
        finishTimerRef.current = null;
      }
      window.removeEventListener("scrollend", finishAnchorScroll);
    }

    function scheduleFinish() {
      if (finishTimerRef.current !== null) {
        window.clearTimeout(finishTimerRef.current);
      }
      window.removeEventListener("scrollend", finishAnchorScroll);
      window.addEventListener("scrollend", finishAnchorScroll, { once: true });
      finishTimerRef.current = window.setTimeout(finishAnchorScroll, 1200);
    }

    function onClick(event: globalThis.MouseEvent) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      if (!(event.target instanceof Element)) return;

      const anchor = event.target.closest<HTMLAnchorElement>('a[href^="#"]');
      if (!anchor || anchor.origin !== window.location.origin || anchor.pathname !== window.location.pathname) return;

      const target = hashTarget(anchor.hash);
      if (!target) return;

      event.preventDefault();
      anchorScrollingRef.current = true;
      window.dispatchEvent(new Event("lp:anchor-scroll-start"));
      window.history.pushState(null, "", `${window.location.pathname}${window.location.search}${anchor.hash}`);

      const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - anchorScrollOffset());
      window.scrollTo({ top, behavior: prefersReducedMotion ? "auto" : "smooth" });

      if (prefersReducedMotion) {
        finishAnchorScroll();
      } else {
        scheduleFinish();
      }
    }

    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("click", onClick);
      finishAnchorScroll();
    };
  }, []);

  return anchorScrollingRef;
}

function StickyBanner({
  anchorScrollingRef,
  onStartTrial,
}: {
  anchorScrollingRef: MutableRefObject<boolean>;
  onStartTrial: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const lastScrollY = useRef(0);
  const visibleRef = useRef(false);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const THRESHOLD = 400;
    const DELTA = 8;

    function setBannerVisible(nextVisible: boolean) {
      if (visibleRef.current === nextVisible) return;
      visibleRef.current = nextVisible;
      setVisible(nextVisible);
    }

    function updateVisibility() {
      frameRef.current = null;
      const current = window.scrollY;
      const delta = current - lastScrollY.current;

      if (anchorScrollingRef.current || current <= THRESHOLD) {
        setBannerVisible(false);
      } else if (delta < -DELTA) {
        setBannerVisible(true);
      } else if (delta > DELTA) {
        setBannerVisible(false);
      }

      lastScrollY.current = current;
    }

    const onScroll = () => {
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(updateVisibility);
    };

    const onAnchorScrollStart = () => {
      lastScrollY.current = window.scrollY;
      setBannerVisible(false);
    };

    lastScrollY.current = window.scrollY;
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("lp:anchor-scroll-start", onAnchorScrollStart);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("lp:anchor-scroll-start", onAnchorScrollStart);
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, [anchorScrollingRef]);

  return (
    <div className={`lp-sticky-banner${visible ? " lp-sticky-banner-visible" : ""}`} aria-hidden={!visible}>
      <div className="lp-sticky-banner-inner">
        <div className="lp-sticky-banner-left">
          <svg className="lp-sticky-mark" width="24" height="18" viewBox="0 0 36 26" aria-hidden="true">
            <path d="M 0,0 L 10,0 L 18,13 L 26,0 L 36,0 L 36,26 L 0,26 Z" fill="currentColor" />
          </svg>
          <span>Cut your AI costs <strong>by up to 43%.</strong></span>
        </div>
        <button className="lp-btn lp-btn-primary lp-btn-cta" onClick={onStartTrial}>
          Start 14-Day Trial
        </button>
      </div>
    </div>
  );
}

function Nav({ onStartFree }: { onStartFree: () => void }) {
  return (
    <header className="lp-nav">
      <div className="lp-container lp-nav-inner">
        <Link className="lp-logo" href="/" aria-label="Varsten home">
          <Image
            src="/logo-varsten-lockup-white.svg"
            alt="Varsten"
            width={190}
            height={28}
            priority
            style={{ width: "100%", height: "auto" }}
          />
        </Link>
        <nav className="lp-nav-center" aria-label="Primary">
          <a href="#how-it-works">Product</a>
          <a href="#pricing">Pricing</a>
          <Link href="/docs">Docs</Link>
          <Link href="/security">Security</Link>
        </nav>
        <div className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>
            Sign in
          </a>
          <button className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" onClick={onStartFree}>
            Start Free
          </button>
        </div>
      </div>
    </header>
  );
}

function ProductShotPlaceholder() {
  return (
    <div className="lp-product-shot" aria-label="Varsten command center preview">
      <div className="lp-browser-bar">
        <div className="lp-browser-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="lp-url-pill">app.varsten.ai/command-center</div>
      </div>
      <div className="lp-dashboard-body">
        <aside className="lp-dashboard-sidebar" aria-hidden="true">
          <div className="lp-sidebar-logo">
            <span />
            <b>varsten</b>
          </div>
          <i />
          <i />
          <i />
          <i />
        </aside>
        <div className="lp-dashboard-main">
          <div className="lp-dashboard-topline" aria-hidden="true">
            <span />
            <span />
          </div>
        <div className="lp-metric-grid">
          {metricCards.map((metric) => (
            <div className="lp-metric-card" key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small className={metric.positive ? "positive" : undefined}>{metric.note}</small>
            </div>
          ))}
        </div>
        <div className="lp-dashboard-panels">
          <div className="lp-dashboard-panel wide">
            <span>Command center</span>
            <div className="lp-chart-line" aria-hidden="true" />
            <i />
            <b />
          </div>
          <div className="lp-dashboard-panel">
            <span>Models</span>
            <div className="lp-model-stack" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <i />
            <b />
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}

function Hero({ onStartFree, onWatchDemo }: { onStartFree: () => void; onWatchDemo: () => void }) {
  return (
    <section className="lp-hero">
      <Terrain variant="hero" />
      <div className="lp-container lp-hero-grid">
        <div className="lp-hero-copy">
          <h1 className="lp-hero-title">
            <span className="lp-hero-title-line">
              Reduce AI <span className="lp-hero-title-accent">spend</span>
            </span>
            <span className="lp-hero-title-line">without sacrificing quality.</span>
          </h1>
          <p className="lp-hero-sub">
            Varsten helps your team spend less on AI by reusing safe repeat answers, sending each request to the right
            model, and checking that cost savings do not hurt quality.
          </p>
          <div className="lp-hero-cta">
            <button className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" onClick={onStartFree}>
              Start Free
            </button>
            <button className="lp-btn lp-btn-ghost lp-btn-lg lp-btn-cta" onClick={onWatchDemo}>
              Watch Demo
            </button>
          </div>
        </div>

        <div className="lp-hero-visual">
          <ProductShotPlaceholder />
        </div>
      </div>
    </section>
  );
}

function Mechanism() {
  return (
    <section className="lp-section lp-section-proxy" id="how-it-works">
      <Terrain variant="proxy" />
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Drop-in proxy</p>
          <h2 className="lp-section-title">
            <span className="lp-title-accent">One line</span> to integrate.
          </h2>
          <p className="lp-section-sub">
            Keep your provider SDK. Point its base URL at Varsten and swap the key. Streaming, tool calls, and your
            existing code stay exactly as they are.
          </p>
        </div>

        <div className="lp-code">
          <div className="lp-code-head">
            <span className="red" />
            <span className="yellow" />
            <span className="green" />
            <span className="lp-code-file">client.py</span>
          </div>
          <pre>
            <code>
              {`from openai import OpenAI

client = OpenAI(
    base_url=`}
              <span className="lp-code-em">&quot;https://proxy.varsten.ai/v1&quot;</span>
              {`,  `}
              <span className="lp-code-mut"># was https://api.openai.com/v1</span>
              {`
    api_key=`}
              <span className="lp-code-em">os.environ[&quot;VARSTEN_API_KEY&quot;]</span>
              {`,  `}
              <span className="lp-code-mut"># your Varsten key</span>
              {`
)

stream = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    stream=True,
)`}
            </code>
          </pre>
        </div>
      </div>
    </section>
  );
}

function Feature({
  eyebrow,
  title,
  body,
  chip,
  id,
  reverse,
  visual,
}: {
  eyebrow: string;
  title: string;
  body: string;
  chip: string;
  id?: string;
  reverse?: boolean;
  visual: "reuse" | "evals" | "reliability";
}) {
  return (
    <article className={`lp-feature${reverse ? " rev" : ""}`} id={id}>
      <Terrain variant="feature" />
      <div className="lp-container lp-feature-inner">
        <div className="lp-feature-text">
          <p className="lp-eyebrow muted">{eyebrow}</p>
          <h3>{title}</h3>
          <p>{body}</p>
        </div>
        <div className={`lp-feature-visual lp-feature-visual-${visual}`} aria-hidden="true">
          <div className="lp-feature-window">
            <div className="lp-feature-window-head">
              <span />
              <span />
              <span />
            </div>
            <div className="lp-feature-window-grid">
              <i />
              <i />
              <i />
              <i />
            </div>
            <div className="lp-feature-window-chart">
              <i />
              <i />
              <i />
            </div>
          </div>
          <span className="lp-feature-chip">
            <span className="dot" />
            <b>{chip}</b>
          </span>
        </div>
      </div>
    </article>
  );
}

function Features() {
  return (
    <section className="lp-features-section" id="features">
      <Feature
        id="response-reuse"
        eyebrow="Response reuse"
        title="Repeat work does not need a new model call."
        body="When the same request shows up again, Varsten can serve the stored response instead of paying for another completion. Near-duplicate matching can be enabled only on routes where it is safe; otherwise the request streams straight through untouched."
        chip="repeat response · $0 · <1 ms"
        visual="reuse"
      />
      <Feature
        reverse
        id="routing-evals"
        eyebrow="Routing & evals"
        title="A cheaper model ships only when the numbers say it's safe."
        body="Before a route moves to a smaller model, Varsten replays your real traffic through both and grades them with a position-swapped judge. Savings are measured as an A/B difference against a concurrent holdback and reported with confidence intervals - not an estimate. If quality slips past tolerance, the route rolls back."
        chip="swap · quality held · CI reported"
        visual="evals"
      />
      <Feature
        id="reliability"
        eyebrow="Reliability"
        title="Inline, but it can't take you down."
        body="The data plane fails open. If anything upstream is unreachable, requests pass through to your original provider unchanged - you stop saving, you never stop serving. Strict read and total timeouts mean a hung upstream can't pin a connection."
        chip="fail-open · strict timeouts"
        visual="reliability"
      />
    </section>
  );
}

type PlanProps = {
  name: string;
  price: string;
  priceNote: string;
  body: string;
  features: string[];
  cta: string;
  featured?: boolean;
  tag?: string;
  onCtaClick: () => void;
  subCta?: string;
  onSubCtaClick?: () => void;
};

function PlanFeatureList({ features }: { features: string[] }) {
  return (
    <ul className="lp-checks">
      {features.map((feature) => (
        <li className="lp-check-item" key={feature}>
          <Check />
          {feature}
        </li>
      ))}
    </ul>
  );
}

function Plan(props: PlanProps) {
  const { name, price, priceNote, body, features, featured, tag, cta, onCtaClick, subCta, onSubCtaClick } = props;

  return (
    <div className={`lp-plan${featured ? " lp-plan-featured" : ""}`}>
      {tag ? <span className="lp-plan-tag">{tag}</span> : null}
      <div className="lp-plan-name">{name}</div>
      <div className="lp-plan-price">
        {price} <span>{priceNote}</span>
      </div>
      <p className="lp-plan-body">{body}</p>
      <PlanFeatureList features={features} />
      <button className={`lp-btn ${featured ? "lp-btn-dark" : "lp-btn-ghost"}`} onClick={onCtaClick}>
        {cta}
      </button>
      {subCta && onSubCtaClick ? (
        <button className="lp-plan-subcta" onClick={onSubCtaClick}>
          {subCta}
        </button>
      ) : null}
    </div>
  );
}

function Pricing({ onStartFree, onStartPerformance }: { onStartFree: () => void; onStartPerformance: () => void }) {
  return (
    <section className="lp-section lp-pricing" id="pricing">
      <Terrain variant="pricing" />
      <div className="lp-container">
        <div className="lp-section-head center inverted">
          <p className="lp-eyebrow">Pricing</p>
          <h2 className="lp-section-title">
            Pay only when Varsten <span>proves</span> savings.
          </h2>
          <p className="lp-section-sub">
            Start with Free to monitor AI spend and review savings recommendations. Move to Performance when you want
            Varsten to optimize traffic directly: 25% of verified savings, you keep the other 75%.
          </p>
        </div>

        <div className="lp-plans">
          <Plan
            name="Free"
            price="$0"
            priceNote="/mo"
            body="Monitor AI spend, review savings recommendations, and use the Proof dashboard without putting Varsten in the request path."
            cta="Get Free"
            onCtaClick={onStartFree}
            features={planFeatures.free}
          />
          <Plan
            featured
            tag="14-day free trial"
            name="Performance"
            price="25%"
            priceNote="of verified savings"
            body="Automate routing, caching, batching, and model swaps with quality guardrails. After the trial, Varsten charges only from verified savings."
            cta="Start 14-day trial"
            onCtaClick={onStartPerformance}
            subCta="No platform fee during trial. Cancel before day 14."
            features={planFeatures.performance}
          />
        </div>
      </div>
    </section>
  );
}

function PricingCalculator() {
  const [monthlySpend, setMonthlySpend] = useState(25000);
  const grossSavings = monthlySpend * SAVINGS_RATE;
  const varstenFee = grossSavings * VARSTEN_SHARE;
  const customerSavings = grossSavings - varstenFee;
  const annualSavings = customerSavings * 12;
  const rangePercent = Math.round(((monthlySpend - 5000) / 95000) * 100);

  return (
    <section className="lp-calculator" aria-labelledby="pricing-calculator-title">
      <div className="lp-card-head">
        <p className="lp-eyebrow">Interactive calculator</p>
        <h3 id="pricing-calculator-title">Estimate the 75/25 split.</h3>
        <p>Uses a conservative 20% savings assumption. Real billing uses verified savings only, never projections.</p>
      </div>

      <label className="lp-range-label" htmlFor="monthly-ai-spend">
        <span>Estimated monthly AI spend</span>
        <strong>{money.format(monthlySpend)}</strong>
      </label>
      <input
        id="monthly-ai-spend"
        className="lp-range"
        type="range"
        min="5000"
        max="100000"
        step="1000"
        value={monthlySpend}
        onChange={(event) => setMonthlySpend(Number(event.target.value))}
        style={{
          background: `linear-gradient(to right, var(--brand) ${rangePercent}%, rgba(26, 23, 20, 0.14) ${rangePercent}%)`,
        }}
      />
      <div className="lp-range-meta">
        <span>$5k</span>
        <span>$100k+</span>
      </div>

      <div className="lp-calc-results">
        <div>
          <span>Gross savings at 20%</span>
          <strong>{money.format(grossSavings)}/mo</strong>
        </div>
        <div>
          <span>Varsten fee at 25%</span>
          <strong>{money.format(varstenFee)}/mo</strong>
        </div>
        <div className="lp-calc-primary">
          <span>You keep 75%</span>
          <strong>{money.format(customerSavings)}/mo</strong>
        </div>
        <div>
          <span>Annualized net savings</span>
          <strong>{money.format(annualSavings)}/yr</strong>
        </div>
      </div>
    </section>
  );
}

function VerifiedSavings() {
  return (
    <section className="lp-verified" aria-labelledby="verified-savings-title">
      <div className="lp-card-head">
        <p className="lp-eyebrow">Verified savings</p>
        <h3 id="verified-savings-title">What counts as billable proof?</h3>
        <p>Varsten only charges when attribution can defend the delta.</p>
      </div>
      <ul className="lp-checks">
        {savingsRules.map((item) => (
          <li className="lp-check-item" key={item}>
            <Check />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SavingsProofSection() {
  return (
    <section className="lp-section lp-savings-proof" id="savings-proof">
      <Terrain variant="proof" />
      <div className="lp-container">
        <div className="lp-section-head center dark">
          <p className="lp-eyebrow">Savings proof</p>
          <h2 className="lp-section-title">
            See the split <span>before you pay.</span>
          </h2>
          <p className="lp-section-sub">
            The calculator shows the shared-savings economics. The proof rules explain what Varsten can bill and what
            stays off the invoice.
          </p>
        </div>
        <div className="lp-pricing-proof-grid">
          <PricingCalculator />
          <VerifiedSavings />
        </div>

        <aside className="lp-enterprise-callout" aria-labelledby="enterprise-terms-title">
          <div>
            <p className="lp-eyebrow">Enterprise terms</p>
            <h3 id="enterprise-terms-title">Predictable contracts, capped fees.</h3>
            <p>
              High-volume teams can use predictable annual contracts with true-ups, annual fee caps, VPC deployment,
              custom evals, security review, and procurement-friendly billing terms.
            </p>
          </div>
          <div className="lp-enterprise-tags" aria-label="Enterprise options">
            <span>VPC deployment</span>
            <span>Custom evals</span>
            <span>Annual caps</span>
            <span>True-ups</span>
          </div>
        </aside>
      </div>
    </section>
  );
}

function Footer({ onStartTrial }: { onStartTrial: () => void }) {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-wrap">
        <div className="lp-footer-grid">
          <div className="lp-footer-brand">
            <div className="lp-footer-logo" aria-label="Varsten">
              <Image src="/logo-varsten-lockup-white.svg" alt="Varsten" width={192} height={28} />
            </div>
            <p>Reduce AI spend without sacrificing quality. The proxy that proves its savings.</p>
            <button className="lp-btn lp-btn-primary lp-btn-cta" onClick={onStartTrial}>
              Start Free
            </button>
          </div>
          <div>
            <h4>Product</h4>
            <a href="#how-it-works">Drop-in Proxy</a>
            <a href="#response-reuse">Response Reuse</a>
            <a href="#routing-evals">Routing & Evals</a>
            <a href="#savings-proof">Savings Proof</a>
            <a href="#pricing">Pricing</a>
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

export default function LandingPage() {
  const [emailOpen, setEmailOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const anchorScrollingRef = useSmoothHashLinks();

  const openEmail = () => setEmailOpen(true);
  const closeEmail = () => setEmailOpen(false);
  const openDemo = () => setDemoOpen(true);
  const closeDemo = () => setDemoOpen(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    if (params.get("lead") !== "start-free") {
      return;
    }

    params.delete("lead");
    const nextSearch = params.toString();
    const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", nextUrl);
    const timer = window.setTimeout(() => setEmailOpen(true), 0);

    return () => window.clearTimeout(timer);
  }, []);

  return (
    <main className="lp-page">
      <StickyBanner anchorScrollingRef={anchorScrollingRef} onStartTrial={openEmail} />
      <Nav onStartFree={openEmail} />
      <Hero onStartFree={openEmail} onWatchDemo={openDemo} />
      <Mechanism />
      <Features />
      <Pricing onStartFree={openEmail} onStartPerformance={openEmail} />
      <SavingsProofSection />
      <Footer onStartTrial={openEmail} />

      {emailOpen && <EmailModal onClose={closeEmail} />}
      {demoOpen && <DemoModal onClose={closeDemo} />}
    </main>
  );
}
