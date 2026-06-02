"use client";

import Link from "next/link";
import { RequireSession } from "@/components/RequireSession";

type Tab = {
  href: string;
  label: string;
};

type Panel = {
  label: string;
  value: string;
  detail: string;
};

type PageConfig = {
  section: string;
  title: string;
  eyebrow: string;
  description: string;
  tabs?: Tab[];
  activeHref?: string;
  panels: Panel[];
  decisions: string[];
};

const TABS: Record<string, Tab[]> = {
  engine: [
    { href: "/engine/recommendations", label: "Recommendations" },
    { href: "/engine/levers", label: "Levers" },
    { href: "/engine/automation", label: "Automation" },
  ],
  guardrails: [
    { href: "/guardrails/quality", label: "Quality" },
    { href: "/guardrails/budgets", label: "Budgets" },
    { href: "/guardrails/alerts", label: "Alerts" },
  ],
  proof: [
    { href: "/proof/savings", label: "Savings" },
    { href: "/proof/attribution", label: "Attribution" },
    { href: "/proof/data-quality", label: "Data quality" },
  ],
  analysis: [
    { href: "/analysis/spend", label: "Spend" },
    { href: "/analysis/customers", label: "Customers" },
    { href: "/analysis/models", label: "Models" },
  ],
  admin: [
    { href: "/admin/connections", label: "Connections" },
    { href: "/admin/team", label: "Team" },
    { href: "/admin/billing-security", label: "Billing & security" },
  ],
};

const CONFIGS: Record<string, PageConfig> = {
  "command-center": {
    section: "Operate",
    title: "Command Center",
    eyebrow: "What should I do right now?",
    description:
      "Live savings, decision queue, recent engine actions, and the largest waste source in one operating view.",
    panels: [
      { label: "Saved this month", value: "$4.8K", detail: "estimated and backtested v1 proof" },
      { label: "Annual run-rate", value: "$58K", detail: "current savings pace" },
      { label: "Decision queue", value: "5", detail: "open cuts awaiting review" },
      { label: "Trust score", value: "92%", detail: "priced and tagged usage coverage" },
    ],
    decisions: [
      "Approve low-risk cache and batch opportunities directly from this page.",
      "Review medium-risk routing or model-change opportunities in Engine.",
      "Open Proof when finance needs the savings methodology.",
    ],
  },
  "engine/recommendations": {
    section: "Engine",
    title: "Recommendations",
    eyebrow: "Ranked cuts with dollar impact",
    description: "The engine turns measured usage into specific savings decisions mapped to the five levers.",
    tabs: TABS.engine,
    activeHref: "/engine/recommendations",
    panels: [
      { label: "Smart routing", value: "Approve", detail: "route eligible traffic to lower-cost models" },
      { label: "Semantic cache", value: "Auto", detail: "avoid repeated model calls" },
      { label: "Token trim", value: "Auto", detail: "compress oversized context" },
      { label: "Cheaper model", value: "Approve", detail: "evaluate workload downgrades" },
    ],
    decisions: [
      "Apply, dismiss, or roll back recommendations.",
      "Every recommendation must carry a lever, target, rationale, risk, and estimated savings.",
    ],
  },
  "engine/levers": {
    section: "Engine",
    title: "Levers",
    eyebrow: "The five mechanisms Varsten uses to cut spend",
    description: "Pause, inspect, and compare savings and quality impact by lever.",
    tabs: TABS.engine,
    activeHref: "/engine/levers",
    panels: [
      { label: "Smart routing", value: "On", detail: "medium risk, approve mode" },
      { label: "Semantic cache", value: "On", detail: "low risk, auto mode" },
      { label: "Token trim", value: "On", detail: "low risk, auto mode" },
      { label: "Batching", value: "On", detail: "low risk, auto mode" },
    ],
    decisions: ["Pause a lever globally when risk changes.", "Use Proof to inspect each lever's savings attribution."],
  },
  "engine/automation": {
    section: "Engine",
    title: "Automation",
    eyebrow: "Auto versus approve, per lever",
    description: "Low-risk objective levers default to auto. Routing and model changes default to approval.",
    tabs: TABS.engine,
    activeHref: "/engine/automation",
    panels: [
      { label: "Auto levers", value: "3", detail: "cache, trim, batching" },
      { label: "Approve levers", value: "2", detail: "routing, cheaper model" },
      { label: "Rollback mode", value: "On", detail: "guardrails own safety" },
      { label: "Kill switch", value: "Later", detail: "production data plane scope" },
    ],
    decisions: ["Set whether each lever acts alone or waits for a human.", "Keep v1 honest: automation is simulated control-plane behavior."],
  },
  "guardrails/quality": {
    section: "Guardrails",
    title: "Quality",
    eyebrow: "The floor the engine may never cross",
    description: "Route-level quality gates, minimum model tiers, latency limits, and rollback settings.",
    tabs: TABS.guardrails,
    activeHref: "/guardrails/quality",
    panels: [
      { label: "Eval gates", value: "2", detail: "seeded route-level quality rules" },
      { label: "Auto rollback", value: "On", detail: "configured, not production inline" },
      { label: "Min tier rules", value: "2", detail: "per route" },
      { label: "Latency caps", value: "2", detail: "first-class guardrail" },
    ],
    decisions: ["Define route-specific quality floors before allowing risky cuts.", "Treat latency regressions like quality regressions."],
  },
  "guardrails/budgets": {
    section: "Guardrails",
    title: "Budgets",
    eyebrow: "Caps by team, feature, or customer",
    description: "Budget config gives the engine clear constraints before spend becomes a surprise.",
    tabs: TABS.guardrails,
    activeHref: "/guardrails/budgets",
    panels: [
      { label: "Team caps", value: "1", detail: "support" },
      { label: "Feature caps", value: "1", detail: "research agent" },
      { label: "Customer caps", value: "1", detail: "Nova Labs" },
      { label: "Hard caps", value: "1", detail: "configured only in v1" },
    ],
    decisions: ["Set spend ceilings before forecast alerts fire.", "Use Analysis to decide whether spend is waste or profitable usage."],
  },
  "guardrails/alerts": {
    section: "Guardrails",
    title: "Alerts",
    eyebrow: "When a human needs to know",
    description: "Threshold alerts route budget and trust issues to email or Slack.",
    tabs: TABS.guardrails,
    activeHref: "/guardrails/alerts",
    panels: [
      { label: "Budget alerts", value: "On", detail: "forecast over budget" },
      { label: "Trust alerts", value: "On", detail: "unpriced usage" },
      { label: "Routes", value: "2", detail: "email and Slack" },
      { label: "Noise floor", value: "Low", detail: "engine handles below threshold" },
    ],
    decisions: ["Escalate only when the engine should not act silently.", "Keep alerts tied to money, trust, or safety."],
  },
  "proof/savings": {
    section: "Proof",
    title: "Savings",
    eyebrow: "The board-ready number",
    description: "Counterfactual spend, actual spend, Varsten fee, and net savings after fee.",
    tabs: TABS.proof,
    activeHref: "/proof/savings",
    panels: [
      { label: "Gross saved", value: "$3.2K", detail: "demo proof rows" },
      { label: "Net saved", value: "$2.6K", detail: "after 20% fee assumption" },
      { label: "Methods", value: "3", detail: "direct, backtested, rate delta" },
      { label: "Confidence", value: "Shown", detail: "ranges live in attribution rows" },
    ],
    decisions: ["Show whether savings are estimated, backtested, or measured.", "Never show savings without an attribution method."],
  },
  "proof/attribution": {
    section: "Proof",
    title: "Attribution",
    eyebrow: "How every saved dollar is tied to a lever",
    description: "Savings broken down by action, lever, method, and confidence interval.",
    tabs: TABS.proof,
    activeHref: "/proof/attribution",
    panels: [
      { label: "Semantic cache", value: "$1.8K", detail: "direct avoided calls" },
      { label: "Token trim", value: "$940", detail: "backtested" },
      { label: "Batching", value: "$410", detail: "rate delta" },
      { label: "Holdback", value: "Later", detail: "not claimed in v1" },
    ],
    decisions: ["Tie each savings claim to method and lever.", "Keep live holdback clearly out of v1 scope."],
  },
  "proof/data-quality": {
    section: "Proof",
    title: "Data Quality",
    eyebrow: "Can finance trust the savings number?",
    description: "Coverage, pricing trust, unknown models, and missing metadata.",
    tabs: TABS.proof,
    activeHref: "/proof/data-quality",
    panels: [
      { label: "Pricing coverage", value: "High", detail: "unknown models are surfaced" },
      { label: "Feature tags", value: "Tracked", detail: "metadata quality signal" },
      { label: "Customer tags", value: "Tracked", detail: "margin analysis depends on this" },
      { label: "Environment", value: "Tracked", detail: "guardrails and non-prod spend" },
    ],
    decisions: ["Fix pricing and tagging gaps before defending savings.", "Treat unknown cost as null, never zero."],
  },
  "analysis/spend": {
    section: "Analysis",
    title: "Spend",
    eyebrow: "Supporting investigation, not the destination",
    description: "Spend drivers by team, feature, provider, environment, and request type.",
    tabs: TABS.analysis,
    activeHref: "/analysis/spend",
    panels: [
      { label: "Team", value: "Support", detail: "largest seeded driver" },
      { label: "Feature", value: "Support bot", detail: "high volume route" },
      { label: "Provider", value: "OpenAI", detail: "primary demo provider" },
      { label: "Environment", value: "Prod", detail: "plus staging/development" },
    ],
    decisions: ["Investigate why spend changed.", "Return to Engine to act on the finding."],
  },
  "analysis/customers": {
    section: "Analysis",
    title: "Customers",
    eyebrow: "AI cost against revenue",
    description: "Customer-level AI margin flags profitable and negative-margin accounts.",
    tabs: TABS.analysis,
    activeHref: "/analysis/customers",
    panels: [
      { label: "Revenue rows", value: "3", detail: "seeded customer economics" },
      { label: "Cost rows", value: "3+", detail: "from usage metadata" },
      { label: "Risk flag", value: "Margin", detail: "negative-margin status" },
      { label: "Buyer wedge", value: "Strong", detail: "AI-native gross margin" },
    ],
    decisions: ["Decide whether usage is waste or profitable service cost.", "Protect valuable spend while cutting waste."],
  },
  "analysis/models": {
    section: "Analysis",
    title: "Models",
    eyebrow: "Cost, volume, and swap opportunities",
    description: "Model spend and average cost per request, feeding routing and downgrade recommendations.",
    tabs: TABS.analysis,
    activeHref: "/analysis/models",
    panels: [
      { label: "Frontier", value: "2", detail: "gpt-4o, sonnet" },
      { label: "Small", value: "2", detail: "mini, haiku" },
      { label: "Substitutes", value: "2", detail: "catalog mapped" },
      { label: "Batch rates", value: "2", detail: "mini, haiku" },
    ],
    decisions: ["Use model data to support Engine recommendations.", "Never downgrade without quality guardrails."],
  },
  "admin/connections": {
    section: "Admin",
    title: "Connections",
    eyebrow: "Provider and ingestion setup",
    description: "Provider connection status, SDK/curl ingestion, model mappings, and API keys.",
    tabs: TABS.admin,
    activeHref: "/admin/connections",
    panels: [
      { label: "Providers", value: "3", detail: "OpenAI, Anthropic, Bedrock" },
      { label: "Ingestion", value: "API key", detail: "curl is the v1 SDK" },
      { label: "Mappings", value: "Catalog", detail: "prices live in data" },
      { label: "Mode", value: "Metadata", detail: "no content in v1" },
    ],
    decisions: ["Connect metadata sources.", "Keep setup read-only by default where possible."],
  },
  "admin/team": {
    section: "Admin",
    title: "Team",
    eyebrow: "Users, roles, and keys",
    description: "Team access, API keys, and narrow roles like Proof-only viewer.",
    tabs: TABS.admin,
    activeHref: "/admin/team",
    panels: [
      { label: "Roles", value: "4", detail: "owner, admin, member, proof viewer" },
      { label: "API keys", value: "Project", detail: "one key is fine for v1" },
      { label: "Rotation", value: "Later", detail: "out of current scope" },
      { label: "Access", value: "Org", detail: "tenant-scoped" },
    ],
    decisions: ["Invite the operators and finance viewers.", "Keep enterprise workflows out of v1."],
  },
  "admin/billing-security": {
    section: "Admin",
    title: "Billing & Security",
    eyebrow: "Commercial model and trust posture",
    description: "Verified-savings pricing, savings floor, and security posture for metadata mode.",
    tabs: TABS.admin,
    activeHref: "/admin/billing-security",
    panels: [
      { label: "Plan", value: "Savings", detail: "percentage of verified savings" },
      { label: "Fee", value: "Below savings", detail: "floor protects ROI" },
      { label: "SOC 2", value: "Later", detail: "artifact, not badge" },
      { label: "Content", value: "Not stored", detail: "metadata mode v1" },
    ],
    decisions: ["Make the commercial relationship self-justifying.", "Be explicit about what security artifacts do not exist yet."],
  },
};

export function ProductPage({ pageKey }: { pageKey: keyof typeof CONFIGS }) {
  const config = CONFIGS[pageKey];

  return (
    <RequireSession>
      <div className="view">
        <div className="page-head">
          <div>
            <div className="eyebrow">{config.section}</div>
            <div className="page-title">{config.title}</div>
            <div className="page-sub">{config.eyebrow}</div>
          </div>
          <div className="spacer" />
          <span className="pill neutral">Phase 6 shell</span>
        </div>

        {config.tabs && config.activeHref && (
          <div className="tabs" aria-label={`${config.title} tabs`}>
            {config.tabs.map((tab) => (
              <Link
                key={tab.href}
                href={tab.href}
                className={`tab${tab.href === config.activeHref ? " active" : ""}`}
              >
                {tab.label}
              </Link>
            ))}
          </div>
        )}

        <section className="hero-panel">
          <div>
            <div className="hero-kicker">{config.eyebrow}</div>
            <h1>{config.title}</h1>
            <p>{config.description}</p>
          </div>
          <div className="hero-note">
            Product-shaped API endpoints exist. The next frontend phase wires these panels to live data.
          </div>
        </section>

        <div className="grid kpi-row">
          {config.panels.map((panel) => (
            <div className="card kpi" key={panel.label}>
              <div className="label">{panel.label}</div>
              <div className="value">{panel.value}</div>
              <div className="foot">{panel.detail}</div>
            </div>
          ))}
        </div>

        <div className="grid cols-2">
          <section className="card">
            <div className="card-head">
              <h3>Primary decisions</h3>
              <span className="sub">what this page should help a user decide</span>
            </div>
            <div className="action-list">
              {config.decisions.map((decision) => (
                <div className="action-row" key={decision}>
                  <span className="step-dot" />
                  <span>{decision}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="card card-pad">
            <div className="mini-title">Implementation note</div>
            <p className="muted-copy">
              This route is part of the new engine-first information architecture. It intentionally
              replaces the old analytics-first nav while preserving the legacy pages until the live
              section screens are built.
            </p>
          </section>
        </div>
      </div>
    </RequireSession>
  );
}
