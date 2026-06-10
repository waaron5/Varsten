"use client";

import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode, type RefObject } from "react";
import Link from "next/link";

const APP_URL = "https://app.varsten.ai";
const SAVINGS_RATE = 0.2;
const VARSTEN_SHARE = 0.25;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

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

// ---------- Email capture modal ----------

function EmailSuccess({ email }: { email: string }) {
  return (
    <div className="lp-modal-body">
      <div className="lp-modal-success">
        <div className="lp-modal-success-icon">
          <Check />
        </div>
        <p className="lp-modal-title">We'll be in touch soon.</p>
        <p>
          Keep an eye on <strong>{email}</strong> — someone from Varsten will reach out to get you set up.
        </p>
      </div>
    </div>
  );
}

function EmailForm({
  email,
  inputRef,
  onCancel,
  onEmailChange,
  onSubmit,
}: {
  email: string;
  inputRef: RefObject<HTMLInputElement | null>;
  onCancel: () => void;
  onEmailChange: (email: string) => void;
  onSubmit: (e: FormEvent) => void;
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
      </div>
      <div className="lp-modal-foot">
        <button type="button" className="lp-btn lp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="lp-btn lp-btn-primary" disabled={!email.trim()}>
          Confirm
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
  inputRef,
  submitted,
  onClose,
  onEmailChange,
  onSubmit,
}: {
  email: string;
  inputRef: RefObject<HTMLInputElement | null>;
  submitted: boolean;
  onClose: () => void;
  onEmailChange: (email: string) => void;
  onSubmit: (e: FormEvent) => void;
}) {
  if (submitted) {
    return (
      <>
        <EmailSuccess email={email} />
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
      inputRef={inputRef}
      onCancel={onClose}
      onEmailChange={onEmailChange}
      onSubmit={onSubmit}
    />
  );
}

function EmailModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
  }

  return (
    <ModalShell labelledBy="email-modal-title" onClose={onClose}>
      <EmailModalHeader submitted={submitted} onClose={onClose} />
      <EmailModalContent
        email={email}
        inputRef={inputRef}
        submitted={submitted}
        onClose={onClose}
        onEmailChange={setEmail}
        onSubmit={handleSubmit}
      />
    </ModalShell>
  );
}

// ---------- Demo modal ----------

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

// ---------- Page sections ----------

function Nav({ onStartFree }: { onStartFree: () => void }) {
  return (
    <header className="lp-nav">
      <div className="lp-container lp-nav-inner">
        <Link className="lp-logo" href="/" aria-label="Varsten home">
          <img src="/varsten-lockup-black.svg" alt="Varsten" />
        </Link>
        <nav className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>
            Sign in
          </a>
          <button className="lp-btn lp-btn-primary" onClick={onStartFree}>
            Start Free
          </button>
        </nav>
      </div>
    </header>
  );
}

function Hero({ onStartFree, onWatchDemo }: { onStartFree: () => void; onWatchDemo: () => void }) {
  return (
    <section className="lp-hero">
      <div className="lp-container lp-hero-grid">
        <div className="lp-hero-copy">
          <h1 className="lp-hero-title">
            <span>Reduce AI spend</span> without sacrificing quality.
          </h1>
          <p className="lp-hero-sub">
            Varsten helps your team spend less on AI by reusing safe repeat answers,
            sending each request to the right model, and checking that cost savings do not hurt quality.
          </p>
          <div className="lp-hero-cta">
            <button className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" onClick={onStartFree}>
              Start Free
            </button>
            <button className="lp-btn lp-btn-ghost lp-btn-lg lp-btn-cta" onClick={onWatchDemo}>
              Watch demo
            </button>
          </div>
        </div>

        <div className="lp-proof">
          <div className="lp-proof-frame">
            <div className="lp-proof-chrome">
              <span className="lp-proof-dot" />
              <span className="lp-proof-dot" />
              <span className="lp-proof-dot" />
              <span className="lp-proof-url">app.varsten.ai/command-center</span>
            </div>
            <div className="lp-proof-canvas">
              <div className="lp-ph-row">
                <div className="lp-ph-tile" />
                <div className="lp-ph-tile" />
                <div className="lp-ph-tile" />
                <div className="lp-ph-tile" />
              </div>
              <div className="lp-ph-main">
                <div className="lp-ph-panel">
                  <span className="lp-ph-caption">Command Center</span>
                </div>
                <div className="lp-ph-panel" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Mechanism() {
  return (
    <section className="lp-section alt" id="how-it-works">
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
            <span className="lp-proof-dot" />
            <span className="lp-proof-dot" />
            <span className="lp-proof-dot" />
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
  reverse,
}: {
  eyebrow: string;
  title: string;
  body: string;
  chip: string;
  reverse?: boolean;
}) {
  return (
    <article className={`lp-feature${reverse ? " rev" : ""}`}>
      <div className="lp-feature-text">
        <p className="lp-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      <div className="lp-feature-visual" aria-hidden="true">
        <span className="lp-feature-chip">
          <span className="dot" />
          <b>{chip}</b>
        </span>
      </div>
    </article>
  );
}

function Features() {
  return (
    <section className="lp-section" id="how">
      <div className="lp-container lp-features">
        <Feature
          eyebrow="Response reuse"
          title="Repeat work does not need a new model call."
          body="When the same request shows up again, Varsten can serve the stored response instead of paying for another completion. Near-duplicate matching can be enabled only on routes where it is safe; otherwise the request streams straight through untouched."
          chip="repeat response · $0 · <1 ms"
        />
        <Feature
          reverse
          eyebrow="Routing & evals"
          title="A cheaper model ships only when the numbers say it's safe."
          body="Before a route moves to a smaller model, Varsten replays your real traffic through both and grades them with a position-swapped judge. Savings are measured as an A/B difference against a concurrent holdback and reported with confidence intervals — not an estimate. If quality slips past tolerance, the route rolls back."
          chip="swap · quality held · CI reported"
        />
        <Feature
          eyebrow="Reliability"
          title="Inline, but it can't take you down."
          body="The data plane fails open. If anything upstream is unreachable, requests pass through to your original provider unchanged — you stop saving, you never stop serving. Strict read and total timeouts mean a hung upstream can't pin a connection."
          chip="fail-open · strict timeouts"
        />
      </div>
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

function PlanActions({
  cta,
  featured,
  onCtaClick,
  onSubCtaClick,
  subCta,
}: Pick<PlanProps, "cta" | "featured" | "onCtaClick" | "onSubCtaClick" | "subCta">) {
  return (
    <>
      <button className={`lp-btn ${featured ? "lp-btn-primary" : "lp-btn-ghost"}`} onClick={onCtaClick}>
        {cta}
      </button>
      {subCta && onSubCtaClick ? (
        <button className="lp-plan-subcta" onClick={onSubCtaClick}>
          {subCta}
        </button>
      ) : null}
    </>
  );
}

function Plan(props: PlanProps) {
  const { name, price, priceNote, body, features, featured } = props;

  return (
    <div className={`lp-plan${featured ? " lp-plan-featured" : ""}`}>
      {featured ? <span className="lp-plan-tag">Recommended</span> : null}
      <div className="lp-plan-name">{name}</div>
      <div className="lp-plan-price">
        {price} <span>{priceNote}</span>
      </div>
      <p className="lp-plan-body">{body}</p>
      <PlanFeatureList features={features} />
      <PlanActions {...props} />
    </div>
  );
}

function PricingCalculator() {
  const [monthlySpend, setMonthlySpend] = useState(25000);
  const grossSavings = monthlySpend * SAVINGS_RATE;
  const varstenFee = grossSavings * VARSTEN_SHARE;
  const customerSavings = grossSavings - varstenFee;
  const annualSavings = customerSavings * 12;

  return (
    <section className="lp-calculator" aria-labelledby="pricing-calculator-title">
      <div className="lp-card-head">
        <p className="lp-eyebrow">Interactive calculator</p>
        <h3 id="pricing-calculator-title">Estimate the 75/25 split.</h3>
        <p>
          Uses a conservative 20% savings assumption. Real billing uses verified savings only, never projections.
        </p>
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
        step="5000"
        value={monthlySpend}
        onChange={(event) => setMonthlySpend(Number(event.target.value))}
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
        {[
          "Cached repeat responses where the avoided model call cost is known.",
          "Batch routing measured as sync price minus batch price.",
          "Routing and model swaps measured against a live holdback or approved eval gate.",
          "Quality guardrails and rollback history attached to each optimization.",
          "Recommendations, estimates, and customer-side changes are not billed.",
        ].map((item) => (
          <li className="lp-check-item" key={item}>
            <Check />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Pricing({ onStartFree, onStartPerformance }: { onStartFree: () => void; onStartPerformance: () => void }) {
  return (
    <section className="lp-section alt" id="pricing">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Pricing</p>
          <h2 className="lp-section-title">
            Pay only when Varsten <span className="lp-title-accent">proves savings.</span>
          </h2>
          <p className="lp-section-sub">
            Start with Free to monitor AI spend month by month and review savings recommendations. Move to
            Performance when you want Varsten to optimize traffic directly: 25% of verified savings, with you keeping
            the other 75%.
          </p>
        </div>

        <div className="lp-plans">
          <Plan
            name="Free"
            price="$0"
            priceNote="/mo"
            body="For teams that need AI spend monitoring and savings recommendations."
            cta="Start Free"
            onCtaClick={onStartFree}
            features={[
              "Ongoing AI spend monitoring",
              "Month-by-month spend trends",
              "Savings recommendations by route, model, and workload",
              "Pricing and catalog trust checks",
              "Read-only Proof dashboard",
            ]}
          />
          <Plan
            featured
            name="Performance"
            price="25%"
            priceNote="of verified savings"
            body="For teams ready to automate savings, billed monthly in arrears only from the dollars it proves."
            cta="Start Performance"
            onCtaClick={onStartPerformance}
            subCta="Start 30-day free trial of Performance"
            onSubCtaClick={onStartPerformance}
            features={[
              "Everything in Free, plus:",
              "Automated routing, caching, batching, and model swaps",
              "Quality guardrails and active rollback",
              "Verified savings ledger",
              "You keep 75% of every verified dollar saved",
              "If Varsten saves $0, you pay $0",
            ]}
          />
        </div>
      </div>
    </section>
  );
}

function SavingsProofSection() {
  return (
    <section className="lp-section lp-pricing-proof-section" id="savings-proof">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Savings proof</p>
          <h2 className="lp-section-title">
            See the split <span className="lp-title-accent">before you pay.</span>
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

function Footer({ onStartTrial, onWatchDemo }: { onStartTrial: () => void; onWatchDemo: () => void }) {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-inner">
        <span>© 2026 Varsten · AI savings engine</span>
        <nav className="lp-footer-links">
          <a href="#how-it-works">Docs</a>
          <a href="#how">Security</a>
          <a href={APP_URL}>Status</a>
          <a href={APP_URL}>Sign in</a>
        </nav>
        <div className="lp-footer-actions">
          <button className="lp-btn lp-btn-ghost" onClick={onWatchDemo}>
            Watch demo
          </button>
          <button className="lp-btn lp-btn-primary" onClick={onStartTrial}>
            Start 30-day trial
          </button>
        </div>
      </div>
    </footer>
  );
}

export default function LandingPage() {
  const [emailOpen, setEmailOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);

  const openEmail = () => setEmailOpen(true);
  const closeEmail = () => setEmailOpen(false);
  const openDemo = () => setDemoOpen(true);
  const closeDemo = () => setDemoOpen(false);

  return (
    <main>
      <Nav onStartFree={openEmail} />
      <Hero onStartFree={openEmail} onWatchDemo={openDemo} />
      <Mechanism />
      <Features />
      <Pricing onStartFree={openEmail} onStartPerformance={openEmail} />
      <SavingsProofSection />
      <Footer onStartTrial={openEmail} onWatchDemo={openDemo} />

      {emailOpen && <EmailModal onClose={closeEmail} />}
      {demoOpen && <DemoModal onClose={closeDemo} />}
    </main>
  );
}
