"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { APP_URL, CONTACT_EMAIL, DPA_REQUEST_HREF, START_FREE_HREF } from "./site-links";

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
  { n: "01", t: "What's driving spend—by model, route, feature, and team?" },
  { n: "02", t: "Where are we paying more for calls that a lower-cost model or cache could handle?" },
  { n: "03", t: "How do we reduce cost without breaking quality or latency?" },
  { n: "04", t: "What savings proof do we have?" },
];

const PROBLEM_SPEND_BARS = [16, 19, 23, 26, 31, 35, 42, 48, 55, 62, 68, 74];
const PROBLEM_CHART_MAX = 80;
const PROBLEM_BUDGET_FRACTION = 0.58;

const SOLUTION = [
  {
    n: "01",
    k: "OBSERVE",
    t: "See where the money goes",
  },
  {
    n: "02",
    k: "OPTIMIZE",
    t: "Cut spend safely",
  },
  {
    n: "03",
    k: "PROVE",
    t: "Prove every dollar",
  },
];

const SOLUTION_BREAKDOWN = [
  { team: "Engineering", pct: 43 },
  { team: "Product", pct: 23 },
  { team: "Data Science", pct: 15 },
];

const LEVERS = [
  { n: "01", t: "Smart routing", d: "Send each request to the most cost-effective model that balances quality and latency." },
  { n: "02", t: "Semantic cache", d: "Stop paying twice for the same answer. Repeated and near-identical requests resolve from cache." },
  { n: "03", t: "Token trim", d: "Cut wasted tokens from prompts and context without changing what the model returns." },
  { n: "04", t: "Model downshift", d: "Downshift to a lower-cost model where it produces equivalent output, and only where it does." },
  { n: "05", t: "Batching", d: "Group eligible requests to capture provider efficiencies and lower per-call cost." },
];

const SECURITY = [
  { t: "Your app keeps working", d: "A failed optimization will never break your app. If Varsten runs into a hiccup or goes offline, requests bypass it and go straight to your regular provider." },
  { t: "The ledger avoids content", d: "The ledger monitors usage, cost, and speed, but does not store prompts or answers. Some optional features like caching hold temporary data based on the retention settings you choose." },
  { t: "Changes are tested first", d: "Varsten tests model changes against a control group behind the scenes. If a new setup doesn't meet your quality standards, it rolls back before affecting a broader audience." },
];

const FAQS = [
  {
    q: "Who does Varsten work best for?",
    a: "Varsten works best for teams with meaningful production LLM traffic. If your traffic is small or experimental, the savings may be too small to justify the integration. If you have a large volume of traffic, Varsten could significantly reduce costs.",
  },
  {
    q: "How much can we expect to save?",
    a: "It depends on your traffic mix. Varsten does not promise a fixed savings percentage. Savings come from cache hits, token reduction, batching, routing, and model changes where they are safe. Observe-only mode is the first step to estimate what is actually available.",
  },
  {
    q: "How are savings verified?",
    a: "Savings are tied to measured usage, provider pricing, and the optimization that produced the change. The ledger separates baseline spend, actual spend, gross savings, Varsten fee, and net customer savings so the math can be inspected.",
  },
  {
    q: "What if we already use the cheapest model?",
    a: "Model downshift may not apply. Varsten can still look for savings from caching, token trim, batching, and routing policies. If there is little safe waste to remove, the product should show that rather than invent savings.",
  },
  {
    q: "What happens if Varsten goes down?",
    a: "The inline path is designed to fail open. Requests continue to the original provider and model where possible, so the application keeps running. During that period you may lose optimization or savings capture, but traffic should not be blocked by Varsten.",
  },
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

function ConfidenceCardHeader() {
  return (
    <>
      <div className="lp-conf-label-row">Data integrity</div>
      <div className="lp-conf-top">
        <div className="lp-conf-badge">
          <span className="lp-conf-check"><Check /></span>
          <div>
            <h3>High confidence</h3>
          </div>
        </div>
        <div className="lp-conf-score"><b>98</b><span> / 100</span></div>
      </div>
    </>
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

function isPlainPrimaryClick(event: globalThis.MouseEvent): boolean {
  const modifierPressed = [event.metaKey, event.ctrlKey, event.shiftKey, event.altKey].some(Boolean);
  return event.button === 0 && !event.defaultPrevented && !modifierPressed;
}

function hashAnchorFromTarget(target: EventTarget | null): HTMLAnchorElement | null {
  if (!(target instanceof Element)) return null;
  return target.closest<HTMLAnchorElement>('a[href^="#"]');
}

function isSamePageAnchor(anchor: HTMLAnchorElement | null): anchor is HTMLAnchorElement {
  return Boolean(anchor && anchor.origin === window.location.origin && anchor.pathname === window.location.pathname);
}

function samePageHashAnchor(event: globalThis.MouseEvent): HTMLAnchorElement | null {
  if (!isPlainPrimaryClick(event)) return null;
  const anchor = hashAnchorFromTarget(event.target);
  return isSamePageAnchor(anchor) ? anchor : null;
}

function scrollDuration(anchor: HTMLAnchorElement): number | null {
  const duration = Number.parseInt(anchor.dataset.scrollDuration ?? "", 10);
  return Number.isFinite(duration) && duration > 0 ? duration : null;
}

function animateScrollTo(top: number, duration: number) {
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
}

function anchorScrollPlan(anchor: HTMLAnchorElement) {
  const target = hashTarget(anchor.hash);
  if (!target) return null;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - anchorScrollOffset());
  return { duration: scrollDuration(anchor), prefersReducedMotion, top };
}

type AnchorScrollPlan = NonNullable<ReturnType<typeof anchorScrollPlan>>;

function executeAnchorScroll(plan: AnchorScrollPlan) {
  if (!plan.prefersReducedMotion && plan.duration) {
    animateScrollTo(plan.top, plan.duration);
    return;
  }
  window.scrollTo({ top: plan.top, behavior: plan.prefersReducedMotion ? "auto" : "smooth" });
}

function beginAnchorScroll(anchor: HTMLAnchorElement, anchorScrollingRef: { current: boolean }) {
  anchorScrollingRef.current = true;
  window.dispatchEvent(new Event("lp:anchor-scroll-start"));
  window.history.pushState(null, "", `${window.location.pathname}${window.location.search}${anchor.hash}`);
}

function useSmoothHashLinks() {
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
      const anchor = samePageHashAnchor(event);
      if (!anchor) return;
      const plan = anchorScrollPlan(anchor);
      if (!plan) return;

      event.preventDefault();
      beginAnchorScroll(anchor, anchorScrollingRef);
      executeAnchorScroll(plan);
      if (plan.prefersReducedMotion) finishAnchorScroll();
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

function useSectionReveal() {
  useEffect(() => {
    const root = document.documentElement;
    const sections = Array.from(document.querySelectorAll<HTMLElement>(".lp-reveal"));
    const revealTargets = sections.map((section) => ({
      section,
      target: section.querySelector<HTMLElement>(":scope > .lp-container") ?? section,
    }));
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    root.classList.add("lp-reveal-ready");

    if (prefersReducedMotion || !("IntersectionObserver" in window)) {
      sections.forEach((section) => section.classList.add("is-visible"));
      return () => root.classList.remove("lp-reveal-ready");
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const match = revealTargets.find(({ target }) => target === entry.target);
          match?.section.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -20% 0px", threshold: 0.08 },
    );

    revealTargets.forEach(({ target }) => observer.observe(target));

    return () => {
      observer.disconnect();
      root.classList.remove("lp-reveal-ready");
    };
  }, []);
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
          <a href="#solution">Product</a>
          <a href="#levers">How it works</a>
          <a href="#pricing">Pricing</a>
          <Link href="/docs">Docs</Link>
        </nav>
        <div className="lp-nav-right">
          <a className="lp-link" href={APP_URL}>Sign in</a>
          <a className="lp-btn lp-btn-ghost" href={`mailto:${CONTACT_EMAIL}`}>Contact sales</a>
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
              <SavingsPanelContent title="Daily Savings" />
            </div>
            <div className="vds-panel">
              <div className="vds-panel-head">
                <div><h5>Savings by lever</h5></div>
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
              <SpendDriversContent meta="By team" title="Spend Drivers" />
            </div>
            <div className="vds-panel vds-panel-proof lp-conf-card">
              <ConfidenceCardHeader />
              <div className="lp-conf-row">
                <span className="name">Pricing coverage</span>
                <span className="stat">100%</span>
              </div>
              <div className="lp-conf-row">
                <span className="name">Spend attribution</span>
                <span className="stat">96.7%</span>
              </div>
              <div className="lp-conf-row">
                <span className="name">Holdback test</span>
                <span className="stat">Live</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SavingsStats() {
  return (
    <div className="vds-stats">
      <div className="vds-stat"><div className="s-label">Avg daily spend</div><div className="s-value">$2,243</div></div>
      <div className="vds-stat pos"><div className="s-label">Avg daily saved</div><div className="s-value">$1,662</div></div>
      <div className="vds-stat"><div className="s-label">Effective rate</div><div className="s-value">42.6%</div></div>
    </div>
  );
}

function SavingsPanelContent({ subtitle, title }: { subtitle?: string; title: string }) {
  return (
    <>
      <div className="vds-panel-head">
        <div>
          <h5>{title}</h5>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        <div className="vds-legend">
          <span><i style={{ background: "var(--chart-spend)" }} />Actual spend</span>
          <span><i style={{ background: "var(--brand)" }} />Savings</span>
        </div>
      </div>
      <SavingsChart />
      <SavingsStats />
    </>
  );
}

function SpendDriversContent({ meta, subtitle, title }: { meta?: string; subtitle?: string; title: string }) {
  return (
    <>
      <div className="vds-panel-head">
        <div>
          <h5>{title}</h5>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {meta ? (
          <span className="meta meta-select">
            {meta}
            <svg aria-hidden="true" viewBox="0 0 16 16">
              <path d="M4 6l4 4 4-4" />
            </svg>
          </span>
        ) : null}
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
    </>
  );
}

/* ── Hero ────────────────────────────────────────────────────── */
function Hero({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-hero lp-reveal">
      <div className="lp-container lp-hero-copy">
        <h1 className="lp-hero-title">
          Cut your AI bill
          <span className="accent">with one line of code</span>
        </h1>
        <p className="lp-hero-sub">
          Varsten is the cost layer for AI. It routes, caches, batches, and trims requests automatically,
          lowering your AI spend without sacrificing output quality.
        </p>
        <div className="lp-hero-cta">
          <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onStart}>Start your 14-day free trial</button>
          <a className="lp-btn lp-btn-ghost lp-btn-lg" href="#levers">See how it works</a>
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

function ProblemSpendChart() {
  const budgetValue = PROBLEM_CHART_MAX * PROBLEM_BUDGET_FRACTION;

  return (
    <div className="lp-problem-chart-card" aria-label="Monthly AI spend climbing into margin">
      <div className="lp-problem-chart-head">
        <div>
          <h3>Monthly AI spend</h3>
        </div>
        <div className="lp-problem-chart-value">
          <strong>$74,180</strong>
          <span>↑ 312% YoY</span>
        </div>
      </div>
      <div className="lp-problem-bars" aria-hidden="true">
        <div className="lp-problem-budget-line" />
        <span className="lp-problem-budget-label">Budget</span>
        {PROBLEM_SPEND_BARS.map((value) => {
          const over = Math.max(0, value - budgetValue);
          const base = value - over;
          const totalHeight = `${(value / PROBLEM_CHART_MAX) * 100}%`;
          const overHeight = `${(over / value) * 100}%`;
          const baseHeight = `${(base / value) * 100}%`;

          return (
            <div className="lp-problem-bar" key={value}>
              <div className="lp-problem-bar-stack" style={{ height: totalHeight }}>
                <div className="lp-problem-bar-over" style={{ height: overHeight }} />
                <div className="lp-problem-bar-base" style={{ height: baseHeight }} />
              </div>
            </div>
          );
        })}
      </div>
      <div className="lp-problem-legend">
        <span><i className="base" />Within budget</span>
        <span><i className="over" />Eating margin</span>
      </div>
    </div>
  );
}

function SolutionPreview({ kind }: { kind: string }) {
  if (kind === "OBSERVE") {
    return (
      <div className="lp-step-chip">
        <div className="lp-step-chip-kicker">Spend by team</div>
        <div className="lp-step-chip-rows">
          {SOLUTION_BREAKDOWN.map((row) => (
            <div className="lp-step-chip-row" key={row.team}>
              <span>{row.team}</span>
              <i><b style={{ width: `${row.pct}%` }} /></i>
              <em>{row.pct}%</em>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (kind === "OPTIMIZE") {
    return (
      <div className="lp-step-chip lp-step-chip-guardrail">
        <div>
          <strong>
            <svg className="lp-scissors-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="6" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M20 4 8.12 15.88" />
              <path d="M14.47 14.48 20 20" />
              <path d="M8.12 8.12 12 12" />
            </svg>
            Token trimming
          </strong>
          <span>Within limits · rollback on</span>
        </div>
        <i aria-hidden="true"><b /></i>
      </div>
    );
  }

  return (
    <div className="lp-step-chip lp-step-chip-ledger">
      <div className="lp-step-chip-ledger-head">
        <span>Net saved · MTD</span>
        <b>Confidence</b>
      </div>
      <div className="lp-step-chip-ledger-row">
        <strong>$23,678</strong>
        <em>98/100</em>
      </div>
    </div>
  );
}

/* ── Problem ─────────────────────────────────────────────────── */
function Problem() {
  return (
    <section className="lp-section lp-problem-section lp-reveal" id="problem">
      <div className="lp-container">
        <div className="lp-problem-layout">
          <div className="lp-problem-copy">
            <div className="lp-section-head">
              <p className="lp-eyebrow">The problem</p>
              <h2 className="lp-section-title">AI spend is now COGS</h2>
              <p className="lp-section-sub">
                It scales with usage, hits gross margin, and lands in board decks. The problem isn&apos;t
                just that the bill is high. It&apos;s that teams can&apos;t
                see what drives it, cut it safely, or prove the savings.
              </p>
            </div>
          </div>
          <div className="lp-problem-visuals">
            <ProblemSpendChart />
            <div className="lp-problem-question-card">
              {PROBLEMS.map((p) => (
                <div className="lp-problem-question-row" key={p.n}>
                  <span className="lp-num">{p.n}</span>
                  <p>{p.t}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Solution ────────────────────────────────────────────────── */
function Solution() {
  return (
    <section className="lp-section lp-solution-section lp-reveal" id="solution">
      <div className="lp-container">
        <div className="lp-solution-layout">
          <div className="lp-section-head lp-solution-head">
            <p className="lp-eyebrow">The solution</p>
            <h2 className="lp-section-title">Automated cost optimization</h2>
            <p className="lp-section-sub">
              Varsten sits between your app and your AI providers so you can see spend clearly, reduce it safely, and
              get proof of savings.
            </p>
          </div>
          <div className="lp-solution-journey">
            {SOLUTION.map((s, index) => (
              <div className="lp-step-card" key={s.n}>
                <div className="lp-step-top">
                  <span className="lp-step-num">{index + 1}</span>
                  <h3>{s.t}</h3>
                </div>
                <SolutionPreview kind={s.k} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Inside the product ──────────────────────────────────────── */
function ProductInside() {
  return (
    <section className="lp-section lp-reveal" id="product">
      <div className="lp-container">
        <div className="lp-product-layout">
          <div className="lp-section-head lp-product-head">
            <p className="lp-eyebrow">Inside the product</p>
            <h2 className="lp-section-title">Every view in one place</h2>
            <p className="lp-section-sub">
              Each dollar of spend is attributed to a model, route, feature, team, and
              pricing source. No estimating. The full picture.
            </p>
          </div>
          <div className="lp-product-grid">
            <div className="lp-card">
              <SavingsPanelContent title="Daily savings" />
            </div>
            <div className="lp-card">
              <SpendDriversContent title="Spend drivers" />
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
    <section className="lp-section lp-reveal" id="levers">
      <div className="lp-container">
        <div className="lp-levers-layout">
          <div className="lp-section-head lp-levers-head">
            <p className="lp-eyebrow">Savings levers</p>
            <h2 className="lp-section-title">Cost cutting in five unique ways</h2>
            <p className="lp-section-sub">
              Each Lever runs behind the same rule: if it risks your quality or latency guardrails, it doesn&apos;t run.
              You don&apos;t pay for levers that aren&apos;t actively cutting costs.
            </p>
          </div>
          <div className="lp-lever-list">
            {LEVERS.map((l) => (
              <div className="lp-lever-item" key={l.n}>
                <span className="n">{l.n}</span>
                <div>
                  <h4>{l.t}</h4>
                  <p>{l.d}</p>
                </div>
                <span className="lp-lever-toggle" aria-hidden="true"><i /></span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Ledger ──────────────────────────────────────────────────── */
function Ledger() {
  return (
    <section className="lp-section lp-reveal" id="ledger">
      <div className="lp-container">
        <div className="lp-ledger-layout">
          <div className="lp-section-head lp-ledger-head-copy">
            <p className="lp-eyebrow">The ledger</p>
            <h2 className="lp-section-title">Continuous self-auditing</h2>
            <p className="lp-section-sub">
              The ledger shows exactly what changed, how much you saved, and how the number was
              calculated. Usable in finance reviews, board decks, and budget decisions.
            </p>
          </div>
          <div className="lp-ledger-grid">
            <div className="lp-conf-card">
              <ConfidenceCardHeader />
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
      </div>
    </section>
  );
}

/* ── How it works ────────────────────────────────────────────── */
function HowItWorks() {
  return (
    <section className="lp-section lp-reveal" id="how-it-works">
      <div className="lp-container">
        <div className="lp-how-layout">
          <div className="lp-section-head lp-how-head">
            <p className="lp-eyebrow">Installation</p>
            <h2 className="lp-section-title">Simple integration</h2>
            <p className="lp-section-sub">
              Start sending traffic through Varsten with a base URL change. For production-safe fail-open behavior, use the SDK wrapper instead.
            </p>
          </div>
          <div className="lp-code-page">
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
    <section className="lp-section lp-section-cream-2 lp-reveal" id="pricing">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">Pricing</p>
          <h2 className="lp-section-title">Pay from savings</h2>
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

/* ── FAQ ─────────────────────────────────────────────────────── */
function FAQ() {
  return (
    <section className="lp-section lp-faq-section lp-reveal" id="faq">
      <div className="lp-container">
        <div className="lp-section-head center">
          <p className="lp-eyebrow">FAQ</p>
          <h2 className="lp-section-title">Common Questions</h2>
          <p className="lp-section-sub">
            A short reference for security, billing, and production behavior.
          </p>
        </div>
        <div className="lp-faq-list">
          {FAQS.map((item, index) => (
            <details className="lp-faq-item" key={item.q} open={index === 0}>
              <summary>
                <span>{item.q}</span>
                <i aria-hidden="true" />
              </summary>
              <p>{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Security ────────────────────────────────────────────────── */
function Security() {
  return (
    <section className="lp-section lp-reveal" id="security">
      <div className="lp-container">
        <div className="lp-sec-layout">
          <div className="lp-section-head lp-sec-head">
            <p className="lp-eyebrow">Security &amp; trust</p>
            <h2 className="lp-section-title">Production safe rollout</h2>
            <p className="lp-section-sub">Our approach to safety is this: keep your app running smoothly even if varsten goes down, measure savings without storing your data, and verify changes work before they go live.</p>
          </div>
          <div className="lp-sec-content">
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
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Final CTA ───────────────────────────────────────────────── */
function FinalCta({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-final">
      <div className="lp-container">
        <h2>Cut your AI spend,<br /> automate the entire process</h2>
        <p>
          Start free in observe-only mode and find out where your money actually goes. Automate when
          you&apos;re ready, and let the ledger make it&apos;s case.
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
            <a href="mailto:mail@varsten.ai">Contact</a>
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
  useSmoothHashLinks();
  useSectionReveal();
  const startFree = () => {
    window.location.href = START_FREE_HREF;
  };

  return (
    <main className="lp-page">
      <Nav onStart={startFree} />
      <Hero onStart={startFree} />
      <Problem />
      <Solution />
      <ProductInside />
      <Levers />
      <Ledger />
      <HowItWorks />
      <Security />
      <Pricing onStart={startFree} />
      <FAQ />
      <FinalCta onStart={startFree} />
      <Footer />
    </main>
  );
}
