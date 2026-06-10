"use client";

// Varsten public landing page (varsten.ai). Semantic HTML + the Varsten CSS token
// system; no Tailwind / UI library. Copy is deliberately dry and technical.

import { useState, type ReactNode } from "react";
import Link from "next/link";

// Placeholder destinations — wire these to the real app/routes when available.
const APP_URL = "https://app.varsten.ai";
const DEMO_URL = "#demo";
const PERFORMANCE_TRIAL_URL = APP_URL;
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

function Nav() {
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
          <a className="lp-btn lp-btn-primary" href={APP_URL}>
            Start Free
          </a>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
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
            <a className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" href={APP_URL}>
              Start Free
            </a>
            <a className="lp-btn lp-btn-ghost lp-btn-lg lp-btn-cta" href={DEMO_URL}>
              Watch demo
            </a>
          </div>
        </div>

        {/* Proof asset: a framed placeholder ready for a high-resolution Command
            Center screenshot. Renders a faint wireframe of that view until then. */}
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

function Plan({
  name,
  price,
  priceNote,
  body,
  features,
  cta,
  ctaHref,
  featured,
  children,
}: {
  name: string;
  price: string;
  priceNote: string;
  body: string;
  features: string[];
  cta: string;
  ctaHref: string;
  featured?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`lp-plan${featured ? " lp-plan-featured" : ""}`}>
      {featured ? <span className="lp-plan-tag">Recommended</span> : null}
      <div className="lp-plan-name">{name}</div>
      <div className="lp-plan-price">
        {price} <span>{priceNote}</span>
      </div>
      <p className="lp-plan-body">{body}</p>
      <ul className="lp-checks">
        {features.map((f) => (
          <li className="lp-check-item" key={f}>
            <Check />
            {f}
          </li>
        ))}
      </ul>
      {ctaHref.startsWith("/") ? (
        <Link className={`lp-btn ${featured ? "lp-btn-primary" : "lp-btn-ghost"}`} href={ctaHref}>
          {cta}
        </Link>
      ) : (
        <a className={`lp-btn ${featured ? "lp-btn-primary" : "lp-btn-ghost"}`} href={ctaHref}>
          {cta}
        </a>
      )}
      {children}
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

function Pricing() {
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
            ctaHref={APP_URL}
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
            ctaHref={APP_URL}
            features={[
              "Everything in Free, plus:",
              "Automated routing, caching, batching, and model swaps",
              "Quality guardrails and active rollback",
              "Verified savings ledger",
              "You keep 75% of every verified dollar saved",
              "If Varsten saves $0, you pay $0",
            ]}
          >
            <a className="lp-plan-subcta" href={PERFORMANCE_TRIAL_URL}>
              Start 30-day free trial of Performance
            </a>
          </Plan>
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

function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-inner">
        <span>© 2026 Varsten · AI savings engine</span>
        <nav className="lp-footer-links">
          <a href="#how-it-works">Docs</a>
          <a href="#how">Security</a>
          <a href={DEMO_URL}>Status</a>
          <a href={APP_URL}>Sign in</a>
        </nav>
        <div className="lp-footer-actions">
          <a className="lp-btn lp-btn-ghost" href={DEMO_URL}>
            Watch demo
          </a>
          <a className="lp-btn lp-btn-primary" href={PERFORMANCE_TRIAL_URL}>
            Start 30-day trial
          </a>
        </div>
      </div>
    </footer>
  );
}

export default function LandingPage() {
  return (
    <main>
      <Nav />
      <Hero />
      <Mechanism />
      <Features />
      <Pricing />
      <SavingsProofSection />
      <Footer />
    </main>
  );
}
