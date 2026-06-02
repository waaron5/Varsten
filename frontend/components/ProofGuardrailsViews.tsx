"use client";

import Link from "next/link";
import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useSession } from "@/components/session";
import { api } from "@/lib/api";
import { compact, usd } from "@/lib/format";
import type {
  AlertRule,
  BudgetRule,
  ProofAttribution,
  ProofDataQuality,
  ProofSavings,
  QualityGuardrail,
} from "@/lib/types";

const PROOF_TABS = [
  { href: "/proof/savings", label: "Savings" },
  { href: "/proof/attribution", label: "Attribution" },
  { href: "/proof/data-quality", label: "Data quality" },
];

const GUARDRAIL_TABS = [
  { href: "/guardrails/quality", label: "Quality" },
  { href: "/guardrails/budgets", label: "Budgets" },
  { href: "/guardrails/alerts", label: "Alerts" },
];

const LEVER_LABELS: Record<string, string> = {
  token_trim: "Token trim",
  semantic_cache: "Semantic cache",
  batching: "Batching",
  cheaper_model: "Cheaper model",
  smart_routing: "Smart routing",
};

function titleize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function leverLabel(value: string): string {
  return LEVER_LABELS[value] ?? titleize(value);
}

function numberValue(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function percent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${Math.round(n * 100)}%`;
}

function plainPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n}%`;
}

function PageHeader({
  section,
  title,
  description,
  action,
}: {
  section: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <div className="eyebrow">{section}</div>
        <h1 className="page-title">{title}</h1>
        <div className="page-sub">{description}</div>
      </div>
      <div className="spacer" />
      {action}
    </div>
  );
}

function Tabs({ tabs, active }: { tabs: { href: string; label: string }[]; active: string }) {
  return (
    <div className="tabs">
      {tabs.map((tab) => (
        <Link key={tab.href} href={tab.href} className={`tab ${active === tab.href ? "active" : ""}`}>
          {tab.label}
        </Link>
      ))}
    </div>
  );
}

function PageState({
  loading,
  error,
  empty,
  emptyDetail,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: string;
  emptyDetail?: string;
}) {
  if (loading) return <div className="empty"><div className="spinner" /></div>;
  if (error) {
    return (
      <div className="empty">
        <div className="et">Could not load this view</div>
        <div className="es">{error}</div>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="empty">
        <div className="et">{empty}</div>
        {emptyDetail ? <div className="es">{emptyDetail}</div> : null}
      </div>
    );
  }
  return null;
}

function useDeferredLoad(load: () => Promise<void>) {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
}

function QualityBar({ label, value }: { label: string; value: string | number | null | undefined }) {
  const n = Math.max(0, Math.min(100, numberValue(value) * 100));
  return (
    <div className="quality-row">
      <div className="quality-label">
        <span>{label}</span>
        <b>{percent(value)}</b>
      </div>
      <div className="quality-track"><i style={{ width: `${n}%` }} /></div>
    </div>
  );
}

export function ProofSavingsView() {
  return <RequireSession><ProofSavingsBody /></RequireSession>;
}

function ProofSavingsBody() {
  const { activeProjectId, getToken } = useSession();
  const [data, setData] = useState<ProofSavings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.proofSavings(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  const savingsRate = data
    ? numberValue(data.counterfactual_spend_usd) > 0
      ? numberValue(data.gross_savings_usd) / numberValue(data.counterfactual_spend_usd)
      : null
    : null;

  return (
    <div className="view">
      <PageHeader
        section="Proof"
        title="Savings"
        description="Board-ready savings accounting: counterfactual spend, actual spend, Varsten fee, and net to customer."
      />
      <Tabs tabs={PROOF_TABS} active="/proof/savings" />
      {loading || error || !data ? (
        <div className="card"><PageState loading={loading} error={error} empty={!data && !loading ? "No savings proof yet" : undefined} /></div>
      ) : (
        <>
          <div className="grid kpi-row">
            <div className="card kpi">
              <div className="label">Counterfactual spend</div>
              <div className="value">{usd(data.counterfactual_spend_usd, 0)}</div>
              <div className="foot">what the traffic would have cost</div>
            </div>
            <div className="card kpi">
              <div className="label">Actual spend</div>
              <div className="value">{usd(data.actual_spend_usd, 0)}</div>
              <div className="foot">measured optimized spend</div>
            </div>
            <div className="card kpi">
              <div className="label">Gross saved</div>
              <div className="value">{usd(data.gross_savings_usd, 0)}</div>
              <div className="foot">{savingsRate === null ? "no baseline yet" : `${percent(savingsRate)} reduction from baseline`}</div>
            </div>
            <div className="card kpi">
              <div className="label">Net to customer</div>
              <div className="value">{usd(data.net_savings_usd, 0)}</div>
              <div className="foot">after {usd(data.varsten_fee_usd, 0)} Varsten fee</div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Measurement note</h3></div>
            <div className="card-pad muted-copy">{data.measurement_note}</div>
          </div>
        </>
      )}
    </div>
  );
}

export function ProofAttributionView() {
  return <RequireSession><ProofAttributionBody /></RequireSession>;
}

function ProofAttributionBody() {
  const { activeProjectId, getToken } = useSession();
  const [data, setData] = useState<ProofAttribution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.proofAttribution(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  return (
    <div className="view">
      <PageHeader
        section="Proof"
        title="Attribution"
        description="Savings tied back to a lever and measurement method so finance can inspect the claim."
      />
      <Tabs tabs={PROOF_TABS} active="/proof/attribution" />
      <div className="card">
        <div className="card-head"><h3>Savings by lever</h3></div>
        {loading || error || !data ? (
          <PageState loading={loading} error={error} empty={!data && !loading ? "No attribution rows yet" : undefined} />
        ) : data.rows.length === 0 ? (
          <PageState empty="No attribution rows yet" emptyDetail="Applied engine actions will populate lever-level proof." />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Lever</th>
                <th>Method</th>
                <th className="r">Actions</th>
                <th className="r">Gross saved</th>
                <th className="r">Net saved</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={`${row.lever}-${row.measurement_method}`}>
                  <td><div className="name"><span className="dot-ic" style={{ background: "var(--brand)" }} />{leverLabel(row.lever)}</div></td>
                  <td className="muted">{titleize(row.measurement_method)}</td>
                  <td className="r">{row.actions}</td>
                  <td className="r">{usd(row.gross_savings_usd, 0)}</td>
                  <td className="r">{usd(row.net_savings_usd, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data ? <div className="hero-note" style={{ marginTop: 16 }}>{data.methodology}</div> : null}
    </div>
  );
}

export function ProofDataQualityView() {
  return <RequireSession><ProofDataQualityBody /></RequireSession>;
}

function ProofDataQualityBody() {
  const { activeProjectId, getToken } = useSession();
  const [data, setData] = useState<ProofDataQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.proofDataQuality(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  return (
    <div className="view">
      <PageHeader
        section="Proof"
        title="Data Quality"
        description="Pricing and tagging coverage that determines whether the savings number is defensible."
      />
      <Tabs tabs={PROOF_TABS} active="/proof/data-quality" />
      {loading || error || !data ? (
        <div className="card"><PageState loading={loading} error={error} empty={!data && !loading ? "No data quality yet" : undefined} /></div>
      ) : (
        <div className="grid cols-2">
          <div className="card">
            <div className="card-head"><h3>Trust coverage</h3></div>
            <div className="grid kpi-row" style={{ padding: 16, marginBottom: 0 }}>
              <div className="kpi">
                <div className="label">Trust score</div>
                <div className="value">{percent(data.trust_score)}</div>
                <div className="foot">priced usage coverage</div>
              </div>
              <div className="kpi">
                <div className="label">Requests</div>
                <div className="value">{compact(data.requests_month)}</div>
                <div className="foot">month to date</div>
              </div>
              <div className="kpi">
                <div className="label">Priced events</div>
                <div className="value">{compact(data.priced_event_count)}</div>
                <div className="foot">usable for savings proof</div>
              </div>
              <div className="kpi">
                <div className="label">Unpriced events</div>
                <div className="value">{compact(data.unpriced_event_count)}</div>
                <div className="foot">must be remapped or overridden</div>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h3>Metadata coverage</h3></div>
            <div className="quality-list">
              {Object.entries(data.metadata_quality).map(([key, value]) => (
                <QualityBar key={key} label={titleize(key)} value={value} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function GuardrailsQualityView() {
  return <RequireSession><GuardrailsQualityBody /></RequireSession>;
}

function GuardrailsQualityBody() {
  const { activeProjectId, getToken } = useSession();
  const [items, setItems] = useState<QualityGuardrail[]>([]);
  const [route, setRoute] = useState("");
  const [tier, setTier] = useState("");
  const [evalGate, setEvalGate] = useState("");
  const [minScore, setMinScore] = useState("");
  const [latency, setLatency] = useState("");
  const [autoRollback, setAutoRollback] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.guardrailsQuality(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!route.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createQualityGuardrail(await getToken(), activeProjectId ?? undefined, {
        route: route.trim(),
        min_model_tier: tier.trim() || null,
        eval_gate: evalGate.trim() || null,
        min_eval_score: minScore === "" ? null : minScore,
        max_latency_ms: latency === "" ? null : Number(latency),
        auto_rollback_enabled: autoRollback,
        enabled: true,
      });
      setItems((current) => [...current, created].sort((a, b) => a.route.localeCompare(b.route)));
      setRoute("");
      setTier("");
      setEvalGate("");
      setMinScore("");
      setLatency("");
      setAutoRollback(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Guardrails"
        title="Quality"
        description="Route-level floors the engine must respect before any savings cut goes live."
      />
      <Tabs tabs={GUARDRAIL_TABS} active="/guardrails/quality" />
      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h3>Quality guardrails</h3></div>
          {loading || error ? (
            <PageState loading={loading} error={error} />
          ) : items.length === 0 ? (
            <PageState empty="No quality guardrails" emptyDetail="Add route floors before trusting automated savings actions." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Route</th><th>Eval gate</th><th>Min tier</th><th className="r">Latency</th><th className="r">Rollback</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><div className="name">{item.route}</div></td>
                    <td className="muted">{item.eval_gate ?? "-"}</td>
                    <td>{item.min_model_tier ?? "-"}</td>
                    <td className="r">{item.max_latency_ms === null ? "-" : `${item.max_latency_ms}ms`}</td>
                    <td className="r"><span className={`pill ${item.auto_rollback_enabled ? "green" : "neutral"}`}>{item.auto_rollback_enabled ? "On" : "Off"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Add quality floor</h3></div>
          <form className="config-form" onSubmit={create}>
            <input className="input" placeholder="Route, e.g. support.answer" value={route} onChange={(e) => setRoute(e.target.value)} />
            <input className="input" placeholder="Minimum model tier" value={tier} onChange={(e) => setTier(e.target.value)} />
            <input className="input" placeholder="Eval gate" value={evalGate} onChange={(e) => setEvalGate(e.target.value)} />
            <input className="input" placeholder="Minimum eval score" value={minScore} onChange={(e) => setMinScore(e.target.value)} />
            <input className="input" placeholder="Max latency ms" value={latency} onChange={(e) => setLatency(e.target.value)} />
            <label className="check-row">
              <input type="checkbox" checked={autoRollback} onChange={(e) => setAutoRollback(e.target.checked)} />
              Auto rollback when a guardrail fails
            </label>
            <button className="btn primary" disabled={busy || !route.trim()} type="submit">{busy ? "Adding..." : "Add guardrail"}</button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function GuardrailsBudgetsView() {
  return <RequireSession><GuardrailsBudgetsBody /></RequireSession>;
}

function GuardrailsBudgetsBody() {
  const { activeProjectId, getToken } = useSession();
  const [items, setItems] = useState<BudgetRule[]>([]);
  const [ownerType, setOwnerType] = useState<"team" | "feature" | "customer">("team");
  const [ownerKey, setOwnerKey] = useState("");
  const [budget, setBudget] = useState("");
  const [hardCap, setHardCap] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.guardrailsBudgets(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  const monthlyTotal = useMemo(
    () => items.reduce((sum, item) => sum + numberValue(item.monthly_budget_usd), 0),
    [items],
  );

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!ownerKey.trim() || !budget) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createBudgetRule(await getToken(), activeProjectId ?? undefined, {
        owner_type: ownerType,
        owner_key: ownerKey.trim(),
        monthly_budget_usd: budget,
        hard_cap_enabled: hardCap,
        enabled: true,
      });
      setItems((current) => [...current, created]);
      setOwnerKey("");
      setBudget("");
      setHardCap(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Guardrails"
        title="Budgets"
        description="Caps by team, feature, or customer so the engine can prevent surprises before they happen."
      />
      <Tabs tabs={GUARDRAIL_TABS} active="/guardrails/budgets" />
      <div className="grid cols-2">
        <div className="card">
          <div className="card-head">
            <h3>Budget rules</h3>
            <div className="right"><span className="pill neutral">{usd(monthlyTotal, 0)} total cap</span></div>
          </div>
          {loading || error ? (
            <PageState loading={loading} error={error} />
          ) : items.length === 0 ? (
            <PageState empty="No budget rules" emptyDetail="Create caps for teams, features, or customers that need spend control." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Owner</th><th>Type</th><th className="r">Monthly cap</th><th className="r">Hard cap</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><div className="name">{item.owner_key}</div></td>
                    <td className="muted">{titleize(item.owner_type)}</td>
                    <td className="r">{usd(item.monthly_budget_usd, 0)}</td>
                    <td className="r"><span className={`pill ${item.hard_cap_enabled ? "amber" : "neutral"}`}>{item.hard_cap_enabled ? "Hard" : "Review"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Add budget rule</h3></div>
          <form className="config-form" onSubmit={create}>
            <select className="input" value={ownerType} onChange={(e) => setOwnerType(e.target.value as "team" | "feature" | "customer")}>
              <option value="team">Team</option>
              <option value="feature">Feature</option>
              <option value="customer">Customer</option>
            </select>
            <input className="input" placeholder="Owner key" value={ownerKey} onChange={(e) => setOwnerKey(e.target.value)} />
            <input className="input" placeholder="Monthly budget USD" value={budget} onChange={(e) => setBudget(e.target.value)} />
            <label className="check-row">
              <input type="checkbox" checked={hardCap} onChange={(e) => setHardCap(e.target.checked)} />
              Hard cap instead of review threshold
            </label>
            <button className="btn primary" disabled={busy || !ownerKey.trim() || !budget} type="submit">{busy ? "Adding..." : "Add budget"}</button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function GuardrailsAlertsView() {
  return <RequireSession><GuardrailsAlertsBody /></RequireSession>;
}

function GuardrailsAlertsBody() {
  const { activeProjectId, getToken } = useSession();
  const [items, setItems] = useState<AlertRule[]>([]);
  const [alertType, setAlertType] = useState("forecast_over_budget");
  const [thresholdUsd, setThresholdUsd] = useState("");
  const [thresholdPercent, setThresholdPercent] = useState("");
  const [destinationType, setDestinationType] = useState<"email" | "slack">("email");
  const [destination, setDestination] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.guardrailsAlerts(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useDeferredLoad(load);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!alertType.trim() || !destination.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createAlertRule(await getToken(), activeProjectId ?? undefined, {
        alert_type: alertType.trim(),
        threshold_usd: thresholdUsd === "" ? null : thresholdUsd,
        threshold_percent: thresholdPercent === "" ? null : thresholdPercent,
        destination_type: destinationType,
        destination: destination.trim(),
        enabled: true,
      });
      setItems((current) => [created, ...current]);
      setThresholdUsd("");
      setThresholdPercent("");
      setDestination("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Guardrails"
        title="Alerts"
        description="Thresholds that pull in a human for budget, trust, or safety issues."
      />
      <Tabs tabs={GUARDRAIL_TABS} active="/guardrails/alerts" />
      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h3>Alert rules</h3></div>
          {loading || error ? (
            <PageState loading={loading} error={error} />
          ) : items.length === 0 ? (
            <PageState empty="No alert rules" emptyDetail="Add only alerts that require human intervention." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Alert</th><th>Destination</th><th className="r">Threshold</th><th className="r">Status</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><div className="name">{titleize(item.alert_type)}</div></td>
                    <td className="muted">{titleize(item.destination_type)}: {item.destination}</td>
                    <td className="r">
                      {item.threshold_usd !== null ? usd(item.threshold_usd, 0) : ""}
                      {item.threshold_usd !== null && item.threshold_percent !== null ? " / " : ""}
                      {item.threshold_percent !== null ? plainPercent(item.threshold_percent) : ""}
                    </td>
                    <td className="r"><span className={`pill ${item.enabled ? "green" : "neutral"}`}>{item.enabled ? "On" : "Off"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Add alert rule</h3></div>
          <form className="config-form" onSubmit={create}>
            <input className="input" placeholder="Alert type" value={alertType} onChange={(e) => setAlertType(e.target.value)} />
            <input className="input" placeholder="Threshold USD" value={thresholdUsd} onChange={(e) => setThresholdUsd(e.target.value)} />
            <input className="input" placeholder="Threshold percent" value={thresholdPercent} onChange={(e) => setThresholdPercent(e.target.value)} />
            <select className="input" value={destinationType} onChange={(e) => setDestinationType(e.target.value as "email" | "slack")}>
              <option value="email">Email</option>
              <option value="slack">Slack</option>
            </select>
            <input className="input" placeholder="Destination" value={destination} onChange={(e) => setDestination(e.target.value)} />
            <button className="btn primary" disabled={busy || !alertType.trim() || !destination.trim()} type="submit">{busy ? "Adding..." : "Add alert"}</button>
          </form>
        </div>
      </div>
    </div>
  );
}
