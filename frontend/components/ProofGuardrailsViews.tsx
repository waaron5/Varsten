"use client";

import type { FormEvent, ReactNode } from "react";
import { Fragment, useMemo, useState } from "react";
import { AttributionTable } from "@/components/AttributionTable";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import {
  BinaryPill,
  CollectionState,
  numberValue,
  PageHeader,
  PageState,
  percent,
  plainPercent,
  QualityBar,
  Tabs,
  titleize,
} from "@/components/viewPrimitives";
import { api } from "@/lib/api";
import { compact, usd } from "@/lib/format";
import type {
  AlertRule,
  BudgetRule,
  EvalConfig,
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

function QualityGuardrailRow({ item }: { item: QualityGuardrail }) {
  return (
    <tr>
      <td><div className="name">{item.route}</div></td>
      <td className="muted">{item.eval_gate ?? "-"}</td>
      <td>{item.min_model_tier ?? "-"}</td>
      <td className="r">{item.max_latency_ms === null ? "-" : `${item.max_latency_ms}ms`}</td>
      <td className="r">
        <BinaryPill active={item.auto_rollback_enabled} activeLabel="On" inactiveLabel="Off" />
      </td>
    </tr>
  );
}

function BudgetRuleRow({ item }: { item: BudgetRule }) {
  return (
    <tr>
      <td><div className="name">{item.owner_key}</div></td>
      <td className="muted">{titleize(item.owner_type)}</td>
      <td className="r">{usd(item.monthly_budget_usd, 0)}</td>
      <td className="r">
        <BinaryPill active={item.hard_cap_enabled} activeLabel="Hard" inactiveLabel="Review" activeTone="amber" />
      </td>
    </tr>
  );
}

function AlertRuleRow({ item }: { item: AlertRule }) {
  return (
    <tr>
      <td><div className="name">{titleize(item.alert_type)}</div></td>
      <td className="muted">{titleize(item.destination_type)}: {item.destination}</td>
      <td className="r">
        {item.threshold_usd !== null ? usd(item.threshold_usd, 0) : ""}
        {item.threshold_usd !== null && item.threshold_percent !== null ? " / " : ""}
        {item.threshold_percent !== null ? plainPercent(item.threshold_percent) : ""}
      </td>
      <td className="r">
        <BinaryPill active={item.enabled} activeLabel="On" inactiveLabel="Off" />
      </td>
    </tr>
  );
}

function GuardrailTableCard<T>({
  children,
  empty,
  emptyDetail,
  error,
  getKey,
  headers,
  items,
  loading,
  right,
  title,
}: {
  children: (item: T) => ReactNode;
  empty: string;
  emptyDetail: string;
  error: string | null;
  getKey: (item: T) => string;
  headers: ReactNode;
  items: T[] | null;
  loading: boolean;
  right?: ReactNode;
  title: string;
}) {
  return (
    <div className="card">
      <div className="card-head"><h3>{title}</h3>{right}</div>
      <CollectionState loading={loading} error={error} items={items} empty={empty} emptyDetail={emptyDetail}>
        {(rows) => (
          <table className="tbl">
            <thead>{headers}</thead>
            <tbody>{rows.map((item) => <Fragment key={getKey(item)}>{children(item)}</Fragment>)}</tbody>
          </table>
        )}
      </CollectionState>
    </div>
  );
}

export function ProofSavingsView() {
  return <RequireSession><ProofSavingsBody /></RequireSession>;
}

function ProofSavingsBody() {
  const { data, loading, error } = useProjectResource<ProofSavings>(api.proofSavings);

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
  const { data, loading, error } = useProjectResource<ProofAttribution>(api.proofAttribution);

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
        ) : (
          <AttributionTable
            empty="No attribution rows yet"
            emptyDetail="Applied engine actions will populate lever-level proof."
            rows={data.rows}
            showGross
          />
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
  const { data, loading, error } = useProjectResource<ProofDataQuality>(api.proofDataQuality);

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

function EvalHarnessControls() {
  const {
    activeProjectId,
    data: config,
    error,
    getToken,
    loading,
    reload,
    setData: setConfig,
    setError,
  } = useProjectResource<EvalConfig>(api.evalConfig);

  const [route, setRoute] = useState("");
  const [prompt, setPrompt] = useState("");
  const [expected, setExpected] = useState("");
  const [savingGolden, setSavingGolden] = useState(false);
  const [togglingCapture, setTogglingCapture] = useState(false);

  const toggleCapture = async (enabled: boolean) => {
    setTogglingCapture(true);
    setError(null);
    try {
      await api.updateEvalCapture(await getToken(), activeProjectId ?? undefined, enabled);
      setConfig((current) => (current ? { ...current, eval_capture_enabled: enabled } : current));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingCapture(false);
    }
  };

  const addGolden = async (event: FormEvent) => {
    event.preventDefault();
    if (!route.trim() || !prompt.trim() || !expected.trim()) return;
    setSavingGolden(true);
    setError(null);
    try {
      await api.uploadGoldenSamples(await getToken(), activeProjectId ?? undefined, [
        {
          route_key: route.trim(),
          messages: [{ role: "user", content: prompt.trim() }],
          expected_output: expected.trim(),
        },
      ]);
      setRoute("");
      setPrompt("");
      setExpected("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingGolden(false);
    }
  };

  const minSamples = config?.min_samples ?? 0;

  return (
    <div className="grid cols-2">
      <div className="card">
        <div className="card-head"><h3>Eval harness</h3></div>
        <div className="card-pad">
          <label className="check-row">
            <input
              type="checkbox"
              checked={config?.eval_capture_enabled ?? false}
              disabled={loading || togglingCapture}
              onChange={(e) => toggleCapture(e.target.checked)}
            />
            Sample real traffic into the replay corpus
          </label>
          <p className="eval-note">
            Off by default. When on, a sampled, redaction-eligible copy of real prompts and their
            answers is stored (TTL&apos;d, capped per route) so a cheaper-model swap can be proven safe
            on real traffic before it is applied. Golden sets below are the strongest signal and never expire.
          </p>
          {error ? <p className="form-error">{error}</p> : null}
          {config && config.routes.length > 0 ? (
            <table className="tbl">
              <thead><tr><th>Route</th><th className="r">Traffic</th><th className="r">Golden</th><th className="r">Ready</th></tr></thead>
              <tbody>
                {config.routes.map((r) => {
                  const ready = r.traffic_samples + r.golden_samples >= minSamples;
                  return (
                    <tr key={r.route_key}>
                      <td>{r.route_key}</td>
                      <td className="r">{compact(r.traffic_samples)}</td>
                      <td className="r">{compact(r.golden_samples)}</td>
                      <td className="r"><BinaryPill active={ready} activeLabel="Ready" inactiveLabel={`Need ${minSamples}`} inactiveTone="amber" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p className="eval-note">No replay samples yet. Enable capture or add golden samples to build the corpus.</p>
          )}
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>Add golden sample</h3></div>
        <form className="config-form" onSubmit={addGolden}>
          <input className="input" placeholder="Route (model), e.g. gpt-4o" value={route} onChange={(e) => setRoute(e.target.value)} />
          <textarea className="input" placeholder="Prompt (the user message)" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <textarea className="input" placeholder="Expected answer" rows={3} value={expected} onChange={(e) => setExpected(e.target.value)} />
          <button className="btn primary" disabled={savingGolden || !route.trim() || !prompt.trim() || !expected.trim()} type="submit">
            {savingGolden ? "Adding..." : "Add golden sample"}
          </button>
        </form>
      </div>
    </div>
  );
}

export function GuardrailsQualityView() {
  return <RequireSession><GuardrailsQualityBody /></RequireSession>;
}

function GuardrailsQualityBody() {
  const {
    activeProjectId,
    data: items,
    error,
    getToken,
    loading,
    setData: setItems,
    setError,
  } = useProjectResource<QualityGuardrail[]>(api.guardrailsQuality, []);
  const [route, setRoute] = useState("");
  const [tier, setTier] = useState("");
  const [evalGate, setEvalGate] = useState("");
  const [minScore, setMinScore] = useState("");
  const [latency, setLatency] = useState("");
  const [autoRollback, setAutoRollback] = useState(true);
  const [busy, setBusy] = useState(false);

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
      setItems((current) => [...(current ?? []), created].sort((a, b) => a.route.localeCompare(b.route)));
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
        <GuardrailTableCard
          title="Quality guardrails"
          loading={loading}
          error={error}
          items={items}
          getKey={(item) => item.id}
          empty="No quality guardrails"
          emptyDetail="Add route floors before trusting automated savings actions."
          headers={<tr><th>Route</th><th>Eval gate</th><th>Min tier</th><th className="r">Latency</th><th className="r">Rollback</th></tr>}
        >
          {(item) => <QualityGuardrailRow item={item} />}
        </GuardrailTableCard>
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
      <EvalHarnessControls />
    </div>
  );
}

export function GuardrailsBudgetsView() {
  return <RequireSession><GuardrailsBudgetsBody /></RequireSession>;
}

function GuardrailsBudgetsBody() {
  const {
    activeProjectId,
    data: items,
    error,
    getToken,
    loading,
    setData: setItems,
    setError,
  } = useProjectResource<BudgetRule[]>(api.guardrailsBudgets, []);
  const [ownerType, setOwnerType] = useState<"team" | "feature" | "customer">("team");
  const [ownerKey, setOwnerKey] = useState("");
  const [budget, setBudget] = useState("");
  const [hardCap, setHardCap] = useState(false);
  const [busy, setBusy] = useState(false);

  const monthlyTotal = useMemo(
    () => (items ?? []).reduce((sum, item) => sum + numberValue(item.monthly_budget_usd), 0),
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
      setItems((current) => [...(current ?? []), created]);
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
        <GuardrailTableCard
          title="Budget rules"
          loading={loading}
          error={error}
          items={items}
          getKey={(item) => item.id}
          empty="No budget rules"
          emptyDetail="Create caps for teams, features, or customers that need spend control."
          headers={<tr><th>Owner</th><th>Type</th><th className="r">Monthly cap</th><th className="r">Hard cap</th></tr>}
          right={<div className="right"><span className="pill neutral">{usd(monthlyTotal, 0)} total cap</span></div>}
        >
          {(item) => <BudgetRuleRow item={item} />}
        </GuardrailTableCard>
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
  const {
    activeProjectId,
    data: items,
    error,
    getToken,
    loading,
    setData: setItems,
    setError,
  } = useProjectResource<AlertRule[]>(api.guardrailsAlerts, []);
  const [alertType, setAlertType] = useState("forecast_over_budget");
  const [thresholdUsd, setThresholdUsd] = useState("");
  const [thresholdPercent, setThresholdPercent] = useState("");
  const [destinationType, setDestinationType] = useState<"email" | "slack">("email");
  const [destination, setDestination] = useState("");
  const [busy, setBusy] = useState(false);

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
      setItems((current) => [created, ...(current ?? [])]);
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
        <GuardrailTableCard
          title="Alert rules"
          loading={loading}
          error={error}
          items={items}
          getKey={(item) => item.id}
          empty="No alert rules"
          emptyDetail="Add only alerts that require human intervention."
          headers={<tr><th>Alert</th><th>Destination</th><th className="r">Threshold</th><th className="r">Status</th></tr>}
        >
          {(item) => <AlertRuleRow item={item} />}
        </GuardrailTableCard>
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
