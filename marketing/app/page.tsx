"use client";

import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { APP_URL, DPA_REQUEST_HREF, START_FREE_HREF } from "./site-links";

/* ── Static data for the dashboard product shot (decorative, fixed numbers) ── */
const LEVER_GROSS_SAVED = 31570;
const LEVER_GROSS_SAVED_LABEL = `$${LEVER_GROSS_SAVED.toLocaleString("en-US")}`;

const KPIS = [
  { label: "Net saved", value: "$23,678", delta: "↑ 18%", hl: true },
  { label: "Gross saved", value: LEVER_GROSS_SAVED_LABEL, delta: "↑ 14%" },
  { label: "Without Varsten", value: "$74,180", delta: "↑ 9%" },
  { label: "Actual spend", value: "$42,610", delta: "↑ 6%" },
];

// Each bar: actual spend (beige) + savings (green), in $K against a $5K axis.
const DAILY_BARS: Array<[number, number]> = [
  [2.0, 1.3], [1.7, 1.1], [2.2, 1.5], [1.9, 1.0], [2.4, 1.7], [2.0, 1.4],
  [1.6, 1.2], [2.3, 1.9], [2.1, 1.5], [1.8, 1.3], [2.5, 2.0], [2.2, 1.6],
  [1.9, 1.4], [2.4, 1.8], [2.0, 1.5], [1.7, 1.1], [2.3, 1.9], [2.1, 1.7], [2.6, 2.2],
];

const LEVER_ROWS = [
  { name: "Semantic cache", state: "Active", amount: "$14,800", pct: 47 },
  { name: "Model downshift", state: "Active", amount: "$11,200", pct: 36 },
  { name: "Batching", state: "Active", amount: "$3,300", pct: 10 },
  { name: "Token trim", state: "Active", amount: "$2,270", pct: 7 },
  { name: "Smart routing", state: "Off", amount: "$0", pct: 0 },
];

const DRIVERS = [
  { team: "Engineering", amount: "$18,300", pct: 42.9, color: "#2B4A5A" },
  { team: "Product", amount: "$9,800", pct: 23.0, color: "#3B6275" },
  { team: "Data Science", amount: "$6,400", pct: 15.0, color: "#4F7A90" },
  { team: "Marketing", amount: "$4,200", pct: 9.9, color: "#6E96AA" },
  { team: "Support", amount: "$2,510", pct: 5.9, color: "#B8CED8" },
  { team: "Untagged", amount: "$1,400", pct: 3.3, color: "#E9F1F5" },
];

const PROBLEMS = [
  { n: "01", t: "What's actually driving spend—by model, route, feature, and team?" },
  { n: "02", t: "Where are you paying premium prices for calls a lower-cost model or cache could handle?" },
  { n: "03", t: "How do you reduce cost without breaking quality or latency?" },
  { n: "04", t: "When the CFO asks if it worked, what proof do you have?" },
];

const SOLUTION = [
  {
    n: "01",
    k: "OBSERVE",
    t: "See where the money goes.",
    d: "Break down spend by model, route, feature, team, and provider. Engineering and finance see the same numbers.",
  },
  {
    n: "02",
    k: "OPTIMIZE",
    t: "Cut spend, safely.",
    d: "Apply caching, batching, trimming, and routing only where quality and latency hold. If output would degrade, it doesn’t run.",
  },
  {
    n: "03",
    k: "PROVE",
    t: "Show your work.",
    d: "Get a finance-ready ledger with gross savings, fees, net savings, and attribution. Every result is easy to explain upstream.",
  },
];

const LEVERS = [
  { n: "01", t: "Smart routing", d: "Send each request to the most cost-effective model that still meets your quality bar, automatically." },
  { n: "02", t: "Semantic cache", d: "Stop paying twice for the same answer. Repeated and near-identical requests resolve from cache." },
  { n: "03", t: "Token trim", d: "Cut wasted tokens from prompts and context without changing what the model returns." },
  { n: "04", t: "Model downshift", d: "Downshift to a lower-cost model where it produces equivalent output, and only where it does." },
  { n: "05", t: "Batching", d: "Group eligible requests to capture provider efficiencies and lower per-call cost." },
];

const HOW_STEPS = [
  { n: 1, t: "Connect", d: "Update the base URL." },
  { n: 2, t: "Optimize", d: "Apply savings levers and guardrails." },
  { n: 3, t: "Prove", d: "Verify your savings with a finance-ready ledger." },
];

const SECURITY = [
  { t: "Fail-open by design", d: "If Varsten has an issue, traffic passes straight through to your providers. Optimization is never a production point of failure." },
  { t: "Never stores prompts or outputs", d: "Varsten records the cost metadata needed to measure savings, without storing your prompts or model outputs." },
  { t: "Quality & latency guardrails", d: "You set the limits. Any optimization that would breach them never fires." },
];

const OBSERVE_FEATURES = [
  "Monitor AI spend and savings opportunities",
  "Verify pricing against provider catalogs",
  "Access a read-only savings dashboard",
  "Includes up to 100,000 observed requests per month",
];
const PERFORMANCE_FEATURES = [
  "Everything in Observe, plus:",
  "Routing, caching, batching, token trimming, and model selection",
  "Quality guardrails and automatic rollback",
  "Finance-grade savings ledger",
  "You keep 75% of every dollar saved",
  "Monthly billing, cancel anytime",
];

/* ── Icons ─────────────────────────────────────────────────── */
function Check({ className = "lp-check" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

const PROVIDER_LOGOS = {
  openai: { src: "/openai.svg", alt: "OpenAI", width: 512, height: 126 },
  anthropic: { src: "/anthropic.svg", alt: "Anthropic", width: 512, height: 58 },
  gemini: { src: "/google-gemini.svg", alt: "Google Gemini", width: 512, height: 188 },
} as const;

function ProviderLogo({ provider }: { provider: keyof typeof PROVIDER_LOGOS }) {
  const logo = PROVIDER_LOGOS[provider];

  return (
    <Image
      className={`provider-logo provider-logo-${provider}`}
      src={logo.src}
      width={logo.width}
      height={logo.height}
      alt={logo.alt}
    />
  );
}

function Logo({ variant = "dark", className = "lp-logo-img" }: { variant?: "dark" | "light"; className?: string }) {
  return (
    <Image
      className={className}
      src={variant === "light" ? "/varsten-logo.svg" : "/varsten-logo-black.svg"}
      width={458}
      height={93}
      alt=""
      aria-hidden="true"
    />
  );
}

function LogoMark({ className = "lp-logo-mark" }: { className?: string }) {
  return <Image className={className} src="/varsten-icon.svg" width={180} height={171} alt="" aria-hidden="true" loading="eager" />;
}

/* ── Smooth anchor scrolling (preserved from the prior build) ── */
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
      if (finishTimerRef.current !== null) window.clearTimeout(finishTimerRef.current);
      window.removeEventListener("scrollend", finishAnchorScroll);
      window.addEventListener("scrollend", finishAnchorScroll, { once: true });
      finishTimerRef.current = window.setTimeout(finishAnchorScroll, 1200);
    }

    function onClick(event: globalThis.MouseEvent) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
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
      const duration = Number.parseInt(anchor.dataset.scrollDuration ?? "", 10);

      if (!prefersReducedMotion && Number.isFinite(duration) && duration > 0) {
        const start = window.scrollY;
        const distance = top - start;
        const startTime = window.performance.now();
        const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

        function frame(now: number) {
          const progress = Math.min(1, (now - startTime) / duration);
          window.scrollTo({ top: start + distance * ease(progress), behavior: "auto" });
          if (progress < 1) window.requestAnimationFrame(frame);
        }

        window.requestAnimationFrame(frame);
      } else {
        window.scrollTo({ top, behavior: prefersReducedMotion ? "auto" : "smooth" });
      }

      if (prefersReducedMotion) finishAnchorScroll();
      else scheduleFinish();
    }

    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("click", onClick);
      finishAnchorScroll();
    };
  }, []);

  return anchorScrollingRef;
}

/* ── Sticky scroll-up banner ─────────────────────────────────── */
function StickyBanner({ anchorScrollingRef, onStart }: { anchorScrollingRef: MutableRefObject<boolean>; onStart: () => void }) {
  const [visible, setVisible] = useState(false);
  const lastScrollY = useRef(0);
  const visibleRef = useRef(false);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const THRESHOLD = 600;
    const DELTA = 8;

    function setBannerVisible(next: boolean) {
      if (visibleRef.current === next) return;
      visibleRef.current = next;
      setVisible(next);
    }

    function update() {
      frameRef.current = null;
      const current = window.scrollY;
      const delta = current - lastScrollY.current;
      if (anchorScrollingRef.current || current <= THRESHOLD) setBannerVisible(false);
      else if (delta < -DELTA) setBannerVisible(true);
      else if (delta > DELTA) setBannerVisible(false);
      lastScrollY.current = current;
    }

    const onScroll = () => {
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(update);
    };
    const onAnchorStart = () => {
      lastScrollY.current = window.scrollY;
      setBannerVisible(false);
    };

    lastScrollY.current = window.scrollY;
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("lp:anchor-scroll-start", onAnchorStart);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("lp:anchor-scroll-start", onAnchorStart);
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
    };
  }, [anchorScrollingRef]);

  return (
    <div className={`lp-sticky-banner${visible ? " lp-sticky-banner-visible" : ""}`} aria-hidden={!visible}>
      <div className="lp-sticky-banner-inner">
        <div className="lp-sticky-banner-left">
          <LogoMark className="lp-logo-mark lp-sticky-mark" />
          <span>Cut your AI bill. <strong>Prove every dollar.</strong></span>
        </div>
        <button className="lp-btn lp-btn-primary" onClick={onStart}>Start free</button>
      </div>
    </div>
  );
}

/* ── Nav ─────────────────────────────────────────────────────── */
function Nav({ onStart }: { onStart: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`lp-nav${scrolled ? " scrolled" : ""}`}>
      <div className="lp-container lp-nav-inner">
        <Link className="lp-logo" href="/" aria-label="Varsten home">
          <Logo />
        </Link>
        <nav className="lp-nav-center" aria-label="Primary">
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#ledger">Proof</a>
          <a href="#pricing">Pricing</a>
        </nav>
        <div className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>Sign in</a>
          <button className="lp-btn lp-btn-primary" onClick={onStart}>Start free</button>
        </div>
      </div>
    </header>
  );
}

/* ── Dashboard product shot ──────────────────────────────────── */
function SavingsChart() {
  return (
    <div className="vchart" aria-hidden="true">
      {DAILY_BARS.map(([spend, save], i) => (
        <div className="vbar" key={i}>
          <div className="seg seg-save" style={{ height: `${(save / 5) * 100}%` }} />
          <div className="seg seg-spend" style={{ height: `${(spend / 5) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

function DashboardShot() {
  return (
    <div className="vds" aria-label="Varsten dashboard preview" role="img">
      <div className="vds-bar">
        <div className="vds-dots"><span /><span /><span /></div>
        <div className="vds-url">app.varsten.ai/dashboard</div>
        <span />
      </div>
      <div className="vds-body">
        <div className="vds-rail">
          <LogoMark className="lp-logo-mark" />
          <i className="on" />
          <i />
          <i />
          <i />
        </div>
        <div className="vds-main">
          <div className="vds-topbar">
            <div>
              <h4>Dashboard</h4>
              <p>Month to date · vs last month</p>
            </div>
            <div className="vds-segments">
              <span className="vds-pill active">Month</span>
              <span className="vds-pill">Quarter</span>
              <span className="vds-pill">Year</span>
            </div>
          </div>
          <div className="vds-kpis">
            {KPIS.map((k) => (
              <div className={`vds-kpi${k.hl ? " hl" : ""}`} key={k.label}>
                <div className="k-label">{k.label}</div>
                <div className="k-value">{k.value}</div>
                <div className="k-delta">{k.delta}</div>
              </div>
            ))}
          </div>
          <div className="vds-panels">
            <div className="vds-panel">
              <div className="vds-panel-head">
                <div>
                  <h5>Daily Savings</h5>
                  <p>Projected cost split into paid spend and saved dollars.</p>
                </div>
                <div className="vds-legend">
                  <span><i style={{ background: "var(--chart-spend)" }} />Actual spend</span>
                  <span><i style={{ background: "var(--brand)" }} />Savings</span>
                </div>
              </div>
              <SavingsChart />
              <div className="vds-stats">
                <div className="vds-stat"><div className="s-label">Avg daily spend</div><div className="s-value">$2,243</div></div>
                <div className="vds-stat pos"><div className="s-label">Avg daily saved</div><div className="s-value">$1,662</div></div>
                <div className="vds-stat"><div className="s-label">Effective rate</div><div className="s-value">42.6%</div></div>
              </div>
            </div>
            <div className="vds-panel">
              <div className="vds-panel-head">
                <div><h5>Savings by lever</h5></div>
                <span className="meta">4 active</span>
              </div>
              <div className="vlever-rows">
                {LEVER_ROWS.slice(0, 4).map((l) => (
                  <div className="vlever" key={l.name}>
                    <div className="vlever-top">
                      <span className="vlever-name">{l.name}</span>
                      <span className="vlever-amt">{l.amount}</span>
                    </div>
                    <div className="vlever-track"><i style={{ width: `${l.pct * 2}%` }} /></div>
                  </div>
                ))}
              </div>
            </div>
            <div className="vds-panel vds-panel-drivers">
              <div className="vds-panel-head">
                <div>
                  <h5>Spend Drivers</h5>
                  <p>Where $42,610 of actual spend was allocated.</p>
                </div>
                <span className="meta">By team</span>
              </div>
              <div className="vdrivers-bar">
                {DRIVERS.map((d) => (
                  <i key={d.team} style={{ width: `${d.pct}%`, background: d.color }} />
                ))}
              </div>
              <div className="vdriver-rows">
                {DRIVERS.map((d) => (
                  <div className="vdriver" key={d.team}>
                    <span className="d-name"><i style={{ background: d.color }} />{d.team}</span>
                    <span className="d-amt">{d.amount}</span>
                    <span className="d-pct">{d.pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="vds-panel vds-panel-proof">
              <div className="vds-panel-head">
                <div><h5>Data Integrity</h5></div>
                <span className="meta">Audit-ready</span>
              </div>
              <div className="vproof-hero">
                <div className="vproof-main">
                  <span className="vproof-check"><Check /></span>
                  <div>
                    <p className="vproof-kicker">Confidence Score</p>
                    <b>High Confidence</b>
                  </div>
                </div>
                <div className="vproof-score"><strong>98</strong><span>/100</span></div>
              </div>
              <div className="vproof-rows">
                <div className="vproof-row">
                  <span>Pricing coverage</span>
                  <b>100%</b>
                </div>
                <div className="vproof-row">
                  <span>Verified savings</span>
                  <b>{LEVER_GROSS_SAVED_LABEL}</b>
                </div>
                <div className="vproof-row">
                  <span>Spend attribution</span>
                  <b>96.7%</b>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Hero ────────────────────────────────────────────────────── */
function Hero({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-hero">
      <div className="lp-container lp-hero-copy">
        <h1 className="lp-hero-title">
          Cut your AI bill.
          <span className="accent">Prove every dollar.</span>
        </h1>
        <p className="lp-hero-sub">
          Reduce your AI spend by routing requests through the cheapest models and optimizations that still meet
          your quality bar, then proving every dollar saved in a finance-ready ledger.
        </p>
        <div className="lp-hero-cta">
          <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onStart}>Start your 14-day free trial</button>
          <a className="lp-btn lp-btn-ghost lp-btn-lg" href="#ledger">See how the ledger works</a>
        </div>
        <div className="lp-trust-row">
          <span className="lp-trust-item"><Check /> Save $0, pay $0</span>
          <span className="lp-trust-item"><Check /> Fail-open by design</span>
          <span className="lp-trust-item"><Check /> Never stores prompts or outputs</span>
        </div>
        <div className="lp-works-with">
          <span className="label">Compatible with</span>
          <span className="name"><ProviderLogo provider="openai" /></span>
          <span className="name"><ProviderLogo provider="anthropic" /></span>
          <span className="name"><ProviderLogo provider="gemini" /></span>
        </div>
      </div>
      <div className="lp-container lp-hero-shot">
        <DashboardShot />
      </div>
    </section>
  );
}

/* ── Problem ─────────────────────────────────────────────────── */
function Problem() {
  return (
    <section className="lp-section lp-section-cream-2 lp-problem-section" id="problem">
      <div className="lp-container">
        <div className="lp-problem-layout">
          <div className="lp-section-head">
            <p className="lp-eyebrow">The problem</p>
            <h2 className="lp-section-title">When AI becomes COGS, every token shows up in your margin.</h2>
            <p className="lp-section-sub">
              AI spend scales with usage and hits gross margin. The problem isn&apos;t
              that the bill is high. It&apos;s that teams can&apos;t
              see what drives it, cut it safely, or prove the savings.
            </p>
          </div>
          <div className="lp-problem-cards">
            {PROBLEMS.map((p) => (
              <div className="lp-num-card" key={p.n}>
                <span className="lp-num">{p.n}</span>
                <p>{p.t}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="lp-problem-callout">
          <span>
            Most teams answer these with spreadsheets, gut feel, and a quarterly scramble.{" "}
            <span className="accent">That&apos;s not a strategy. It&apos;s exposure.</span>
          </span>
        </div>
      </div>
    </section>
  );
}

/* ── Solution ────────────────────────────────────────────────── */
function Solution() {
  return (
    <section className="lp-section lp-section-dark on-dark lp-solution-section">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">The solution</p>
          <h2 className="lp-section-title">Observe. Optimize. Prove.</h2>
          <p className="lp-section-sub">
            Varsten sits between your app and your AI providers so you can see spend clearly, reduce it safely, and
            prove the savings with records finance can trust.
          </p>
        </div>
        <div className="lp-grid-3">
          {SOLUTION.map((s) => (
            <div className="lp-step-card" key={s.n}>
              <div className="lp-step-top">
                <span className="lp-step-num">{s.n}</span>
                <span className="lp-step-kicker">{s.k}</span>
              </div>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
            </div>
          ))}
        </div>
        <a className="lp-solution-jump" href="#how-it-works" data-scroll-duration="950">
          <span>See how it works</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 5v14" />
            <path d="m19 12-7 7-7-7" />
          </svg>
        </a>
      </div>
    </section>
  );
}

/* ── Inside the product ──────────────────────────────────────── */
function ProductInside() {
  return (
    <section className="lp-section" id="product">
      <div className="lp-container">
        <div className="lp-section-head">
          <p className="lp-eyebrow">Inside the product</p>
          <h2 className="lp-section-title">The finance view and the engineering view, in one place.</h2>
          <p className="lp-section-sub">
            Every dollar of spend is attributed to a model, route, feature, team, and
            pricing source. No estimating. The full picture.
          </p>
        </div>
        <div className="lp-product-grid">
          <div className="lp-card">
            <div className="vds-panel-head">
              <div>
                <h5>Savings</h5>
                <p>Daily. Each bar is what you&apos;d have paid, split into spend &amp; savings.</p>
              </div>
              <div className="vds-legend">
                <span><i style={{ background: "var(--chart-spend)" }} />Actual spend</span>
                <span><i style={{ background: "var(--brand)" }} />Savings</span>
              </div>
            </div>
            <SavingsChart />
            <div className="vchart-x"><span>1</span><span>5</span><span>10</span><span>15</span><span>19</span></div>
            <div className="vds-stats">
              <div className="vds-stat"><div className="s-label">Avg daily spend</div><div className="s-value">$2,243</div></div>
              <div className="vds-stat pos"><div className="s-label">Avg daily saved</div><div className="s-value">$1,662</div></div>
              <div className="vds-stat"><div className="s-label">Effective rate</div><div className="s-value">42.6%</div></div>
            </div>
          </div>
          <div className="lp-card">
            <div className="vds-panel-head">
              <div>
                <h5>Spend drivers</h5>
                <p>Where $42,610 of actual spend went, by team.</p>
              </div>
            </div>
            <div className="vdrivers-bar">
              {DRIVERS.map((d) => (
                <i key={d.team} style={{ width: `${d.pct}%`, background: d.color }} />
              ))}
            </div>
            <div className="vdriver-rows">
              {DRIVERS.map((d) => (
                <div className="vdriver" key={d.team}>
                  <span className="d-name"><i style={{ background: d.color }} />{d.team}</span>
                  <span className="d-amt">{d.amount}</span>
                  <span className="d-pct">{d.pct.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Levers ──────────────────────────────────────────────────── */
function Levers() {
  return (
    <section className="lp-section lp-section-cream-2" id="levers">
      <div className="lp-container">
        <div className="lp-section-head">
          <p className="lp-eyebrow">Savings levers</p>
          <h2 className="lp-section-title">Five ways Varsten lowers your bill, safely.</h2>
          <p className="lp-section-sub">
            Every lever runs behind the same rule: if it risks your quality or latency guardrails, it doesn&apos;t run.
          </p>
        </div>
        <div className="lp-levers-grid">
          <div className="lp-lever-list">
            {LEVERS.map((l) => (
              <div className="lp-lever-item" key={l.n}>
                <span className="n">{l.n}</span>
                <div>
                  <h4>{l.t}</h4>
                  <p>{l.d}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="lp-card lever-panel">
            <div className="vlever-head">
              <h5>Savings by lever</h5>
            </div>
            <div className="vlever-rows">
              {LEVER_ROWS.map((l) => (
                <div className={`vlever${l.state === "Off" ? " is-off" : ""}`} key={l.name}>
                  <div className="vlever-top">
                    <span className="vlever-name">
                      {l.name}
                      <span className={`vstate ${l.state === "Off" ? "off" : "on"}`}>{l.state}</span>
                    </span>
                    <strong className="vlever-amt">{l.amount}</strong>
                  </div>
                  <div className="vlever-bar">
                    <span className="vlever-track"><i style={{ width: `${l.pct}%` }} /></span>
                    <em className="vlever-pct">{l.pct}%</em>
                  </div>
                </div>
              ))}
            </div>
            <div className="vlever-total">
              <span className="t-label">Gross saved</span>
              <span className="t-value">{LEVER_GROSS_SAVED_LABEL}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Ledger ──────────────────────────────────────────────────── */
function Ledger() {
  return (
    <section className="lp-section lp-section-dark on-dark" id="ledger">
      <div className="lp-container">
        <div className="lp-section-head">
          <p className="lp-eyebrow">The ledger</p>
          <h2 className="lp-section-title">Numbers your CFO can stand behind.</h2>
          <p className="lp-section-sub">
            A dashboard shows activity. A ledger shows exactly what changed, how much you saved, and how the number was
            calculated. That is what makes the savings usable in finance reviews, board decks, and budget decisions.
          </p>
        </div>
        <div className="lp-ledger-grid">
          <div className="lp-ledger-card">
            <div className="lp-ledger-head">
              <h3>Savings ledger</h3>
              <span className="meta">Month to date</span>
            </div>
            <div className="lp-ledger-row">
              <span className="label">Gross savings</span>
              <span className="val">{LEVER_GROSS_SAVED_LABEL}</span>
            </div>
            <div className="lp-ledger-row">
              <span className="label">Varsten fee <small>· 25% of verified</small></span>
              <span className="val">&minus;$7,893</span>
            </div>
            <div className="lp-ledger-row net">
              <span className="label">Net savings <small>· what you keep</small></span>
              <span className="val">$23,678</span>
            </div>
            <div className="lp-ledger-meta">
              <div className="row">
                <span className="k">Attribution</span>
                <span className="v">By lever, route &amp; pricing source. 96.7% of spend tagged.</span>
              </div>
              <div className="row">
                <span className="k">Method</span>
                <span className="v">Live holdback A/B + official catalog pricing.</span>
              </div>
            </div>
          </div>
          <div className="lp-conf-card">
            <div className="lp-conf-top">
              <div className="lp-conf-badge">
                <span className="lp-conf-check"><Check /></span>
                <div>
                  <h3>High confidence</h3>
                  <p>Suitable for board reporting &amp; finance sign-off</p>
                </div>
              </div>
              <div className="lp-conf-score"><b>98</b><span> / 100</span></div>
            </div>
            <div className="lp-conf-row">
              <span className="name">Pricing coverage <span className="vstate on">Catalog-verified</span></span>
              <span className="stat">100%</span>
              <span className="desc">Every dollar priced from official provider catalogs.</span>
            </div>
            <div className="lp-conf-row">
              <span className="name">Spend attribution <span className="vstate on">Tagged</span></span>
              <span className="stat">96.7%</span>
              <span className="desc">Share of spend tied to a team or feature.</span>
            </div>
            <div className="lp-conf-row">
              <span className="name">Holdback test <span className="vstate on">Passing</span></span>
              <span className="stat">Live</span>
              <span className="desc">A traffic slice skips Varsten so savings are proven against live behavior, not modeled.</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── How it works ────────────────────────────────────────────── */
function HowItWorks() {
  return (
    <section className="lp-section" id="how-it-works">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">How it works</p>
          <h2 className="lp-section-title">Goes live the same day.</h2>
          <p className="lp-section-sub">
            Point your existing AI traffic through Varsten with a base URL change. No rewrites, no SDK swap.
          </p>
        </div>
        <div className="lp-how-grid">
          <div className="lp-steps">
            {HOW_STEPS.map((s) => (
              <div className="lp-step-row" key={s.n}>
                <span className="badge">{s.n}</span>
                <div>
                  <h4>{s.t}</h4>
                  <p>{s.d}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="lp-code">
            <div className="lp-code-head">
              <span className="r" /><span className="y" /><span className="g" />
              <span className="lp-code-file">client.py</span>
            </div>
            <pre>
              <code>
                <span className="kw">from</span> openai <span className="kw">import</span> OpenAI{"\n\n"}
                client = OpenAI({"\n"}
                {"    "}base_url=<span className="str">&quot;https://proxy.varsten.ai/v1&quot;</span>,{"  "}
                <span className="com"># was api.openai.com/v1</span>{"\n"}
                {"    "}api_key=os.environ[<span className="str">&quot;VARSTEN_KEY&quot;</span>],{"\n"}
                ){"\n\n"}
                <span className="com"># everything else stays the same</span>
              </code>
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Pricing ─────────────────────────────────────────────────── */
function PlanChecks({ items }: { items: string[] }) {
  return (
    <ul className="lp-checks">
      {items.map((f) => (
        <li className="lp-check-item" key={f}>
          <Check />
          {f}
        </li>
      ))}
    </ul>
  );
}

function Pricing({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-section lp-section-cream-2" id="pricing">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Pricing</p>
          <h2 className="lp-section-title">Pay from savings.</h2>
          <p className="lp-section-sub">
            If we save you nothing, you pay nothing.
          </p>
        </div>
        <div className="lp-plans">
          <div className="lp-plan">
            <span className="lp-plan-name">Observe · Free</span>
            <div className="lp-plan-price">$0 <span>/mo</span></div>
            <p className="lp-plan-body">See where the waste is before automating savings.</p>
            <PlanChecks items={OBSERVE_FEATURES} />
            <button className="lp-btn lp-btn-ghost" onClick={onStart}>Explore observe-only mode</button>
          </div>
          <div className="lp-plan featured">
            <span className="lp-plan-tag">RECOMMENDED</span>
            <span className="lp-plan-name">Performance</span>
            <div className="lp-plan-price">25% <span>of verified savings</span></div>
            <p className="lp-plan-body">Automate savings. Billed monthly in arrears.</p>
            <PlanChecks items={PERFORMANCE_FEATURES} />
            <button className="lp-btn lp-btn-primary" onClick={onStart}>Start your 14-day free trial</button>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Security ────────────────────────────────────────────────── */
function Security() {
  return (
    <section className="lp-section" id="security">
      <div className="lp-container">
        <div className="lp-section-head">
          <p className="lp-eyebrow">Security &amp; trust</p>
          <h2 className="lp-section-title">Built for production traffic and security review.</h2>
          <p className="lp-section-sub">Inline by design, but never a single point of failure.<br />
             We measure cost, not content.</p>
        </div>
        <div className="lp-sec-grid">
          {SECURITY.map((claim) => (
            <div className="lp-sec-card" key={claim.t}>
              <span className="lp-sec-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              </span>
              <div>
                <h4>{claim.t}</h4>
                <p>{claim.d}</p>
              </div>
            </div>
          ))}
        </div>
        <p className="lp-sec-support">Prepared for DPA and security review.</p>
      </div>
    </section>
  );
}

/* ── Final CTA ───────────────────────────────────────────────── */
function FinalCta({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-final">
      <div className="lp-container">
        <h2>Cut your AI spend confidently. Automate the entire process.</h2>
        <p>
          Start free in observe-only mode and find out where your money actually goes. Turn on optimization when
          you&apos;re ready, and let the ledger make your case for you.
        </p>
        <div className="lp-final-cta">
          <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onStart}>Start your 14-day free trial</button>
          <button className="lp-btn lp-btn-ghost lp-btn-lg" onClick={onStart}>Explore observe-only mode</button>
        </div>
        <p className="lp-final-note">Pay 25% of verified savings. If we save you nothing, you pay nothing.</p>
      </div>
    </section>
  );
}

/* ── Footer ──────────────────────────────────────────────────── */
function FooterCol({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="lp-footer-col">
      <h4>{title}</h4>
      {children}
    </div>
  );
}

function Footer() {
  return (
    <footer className="lp-footer on-dark">
      <div className="lp-container">
        <div className="lp-footer-grid">
          <div className="lp-footer-brand">
            <Link className="lp-logo" href="/" aria-label="Varsten home">
              <Logo variant="light" />
            </Link>
            <p>Reduce AI spend without sacrificing quality. The inline proxy that proves its savings.</p>
          </div>
          <FooterCol title="Product">
            <a href="#product">Overview</a>
            <a href="#levers">Savings levers</a>
            <a href="#ledger">The ledger</a>
            <a href="#pricing">Pricing</a>
          </FooterCol>
          <FooterCol title="Company">
            <Link href="/docs">Docs</Link>
            <a href="#how-it-works">How it works</a>
          </FooterCol>
          <FooterCol title="Legal">
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/security">Security</Link>
            <a href={DPA_REQUEST_HREF}>DPA</a>
          </FooterCol>
        </div>
        <div className="lp-footer-bottom">
          <span>© 2026 Varsten, Inc. All rights reserved.</span>
        </div>
      </div>
    </footer>
  );
}

/* ── Page ────────────────────────────────────────────────────── */
export default function LandingPage() {
  const anchorScrollingRef = useSmoothHashLinks();
  const startFree = () => {
    window.location.href = START_FREE_HREF;
  };

  return (
    <main className="lp-page">
      <StickyBanner anchorScrollingRef={anchorScrollingRef} onStart={startFree} />
      <Nav onStart={startFree} />
      <Hero onStart={startFree} />
      <Problem />
      <Solution />
      <ProductInside />
      <Levers />
      <Ledger />
      <HowItWorks />
      <Pricing onStart={startFree} />
      <Security />
      <FinalCta onStart={startFree} />
      <Footer />
    </main>
  );
}
