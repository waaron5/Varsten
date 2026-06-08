// Varsten public landing page (varsten.ai). Semantic HTML + the Varsten CSS token
// system; no Tailwind / UI library. Copy is deliberately dry and technical.

import Link from "next/link";

// Placeholder destinations — wire these to the real app/routes when available.
const APP_URL = "https://app.varsten.ai";
const DEMO_URL = "#demo";
const PRICING_URL = "/pricing";

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
          Varsten
        </Link>
        <nav className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>
            Sign in
          </a>
          <a className="lp-btn lp-btn-primary" href={APP_URL}>
            Start for free
          </a>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="lp-hero">
      <div className="lp-container">
        <h1 className="lp-hero-title">Reduce AI spend without sacrificing quality.</h1>
        <p className="lp-hero-sub">
          Varsten is a drop-in AI proxy that automatically caches exact hits, routes traffic to the most
          cost-effective models, and proves safety with concurrent holdback evals.
        </p>
        <div className="lp-hero-cta">
          <a className="lp-btn lp-btn-primary lp-btn-lg lp-btn-cta" href={APP_URL}>
            Start for free
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
    </section>
  );
}

function Mechanism() {
  return (
    <section className="lp-section alt" id="how-it-works">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Drop-in proxy</p>
          <h2 className="lp-section-title">One line to integrate.</h2>
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
          eyebrow="Exact-hash cache"
          title="Identical requests never reach the model twice."
          body="A byte-exact match serves the stored completion in under a millisecond at zero marginal cost. A miss streams straight through, untouched — nothing is buffered, so you never add latency to a real call."
          chip="exact hit · $0 · <1 ms"
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
  features,
  cta,
  ctaHref,
  featured,
}: {
  name: string;
  price: string;
  priceNote: string;
  features: string[];
  cta: string;
  ctaHref: string;
  featured?: boolean;
}) {
  return (
    <div className={`lp-plan${featured ? " lp-plan-featured" : ""}`}>
      {featured ? <span className="lp-plan-tag">Recommended</span> : null}
      <div className="lp-plan-name">{name}</div>
      <div className="lp-plan-price">
        {price} <span>{priceNote}</span>
      </div>
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
    </div>
  );
}

function Pricing() {
  return (
    <section className="lp-section alt" id="pricing">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Pricing</p>
          <h2 className="lp-section-title">Start free. Pay from what you save.</h2>
          <p className="lp-section-sub">
            Connect in minutes, watch the analysis, and run a 30-day savings trial. The paid plan is a share of
            verified savings, so the fee is always smaller than the cut.
          </p>
        </div>

        <div className="lp-plans">
          <Plan
            featured
            name="Start for free"
            price="$0"
            priceNote="to start"
            cta="Deploy free trial"
            ctaHref={APP_URL}
            features={[
              "Free drop-in setup",
              "Free AI spend analysis",
              "30-day automated savings trial",
              "Read-only cost analysis dashboard",
            ]}
          />
          <Plan
            name="Pro"
            price="% of savings"
            priceNote="billed on verified cuts"
            cta="View pricing"
            ctaHref={PRICING_URL}
            features={[
              "Fully autonomous routing",
              "Active auto-rollbacks",
              "Custom model evals",
              "Unlimited proxy bandwidth",
            ]}
          />
        </div>
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
      <Footer />
    </main>
  );
}
