"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useSession } from "@/components/session";
import { api } from "@/lib/api";
import { compact, relativeTime, usd } from "@/lib/format";
import type {
  AutomationLever,
  AutomationMode,
  CommandCenter,
  LeverConfig,
  Recommendation,
  RecommendationAction,
  RecommendationStatus,
} from "@/lib/types";

const ENGINE_TABS = [
  { href: "/engine/recommendations", label: "Recommendations" },
  { href: "/engine/levers", label: "Levers" },
  { href: "/engine/automation", label: "Automation" },
];

const LEVER_LABELS: Record<string, string> = {
  token_trim: "Token trim",
  semantic_cache: "Semantic cache",
  batching: "Batching",
  cheaper_model: "Cheaper model",
  smart_routing: "Smart routing",
};

function leverLabel(lever: string | null | undefined): string {
  if (!lever) return "General";
  return LEVER_LABELS[lever] ?? titleize(lever);
}

function titleize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function pct(value: string | number | null | undefined, scale = 100): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${Math.round(n * scale)}%`;
}

function signedPct(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function riskClass(risk: string): string {
  const normalized = risk.toLowerCase();
  if (normalized.includes("high")) return "amber";
  if (normalized.includes("medium")) return "accent";
  return "green";
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
  if (loading) {
    return (
      <div className="empty">
        <div className="spinner" />
      </div>
    );
  }
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

function EngineTabs({ active }: { active: string }) {
  return (
    <div className="tabs">
      {ENGINE_TABS.map((tab) => (
        <Link key={tab.href} href={tab.href} className={`tab ${active === tab.href ? "active" : ""}`}>
          {tab.label}
        </Link>
      ))}
    </div>
  );
}

function RecommendationCard({
  recommendation,
  busy,
  onStatus,
}: {
  recommendation: Recommendation;
  busy?: boolean;
  onStatus?: (id: string, status: RecommendationStatus) => void;
}) {
  const savings = recommendation.estimated_monthly_savings_usd;
  return (
    <div className="rec-card">
      <div className="rec-main">
        <div className="meta-row">
          <span className="pill accent">{leverLabel(recommendation.lever)}</span>
          <span className={`pill ${riskClass(recommendation.risk_level)}`}>
            {titleize(recommendation.risk_level)} risk
          </span>
          <span className="pill neutral">{pct(recommendation.confidence)} confidence</span>
        </div>
        <h3>{recommendation.title}</h3>
        <p>{recommendation.rationale ?? recommendation.description}</p>
        <div className="rec-meta">
          <span>{recommendation.target_type ? titleize(recommendation.target_type) : "Target"}</span>
          <b>{recommendation.target_key ?? recommendation.related_feature ?? recommendation.related_model ?? "project-wide"}</b>
          <span>Method</span>
          <b>{titleize(recommendation.measurement_method)}</b>
          {recommendation.monthly_request_volume !== null ? (
            <>
              <span>Requests</span>
              <b>{compact(recommendation.monthly_request_volume)}</b>
            </>
          ) : null}
        </div>
      </div>
      <div className="rec-side">
        <div className="rec-money">{savings === null ? "Needs pricing" : usd(savings, 0)}</div>
        <div className="rec-sub">estimated monthly savings</div>
        {onStatus ? (
          <div className="rec-actions">
            <button
              className="btn primary"
              disabled={busy}
              onClick={() => onStatus(recommendation.id, "applied")}
              type="button"
            >
              Apply
            </button>
            <button
              className="btn"
              disabled={busy}
              onClick={() => onStatus(recommendation.id, "dismissed")}
              type="button"
            >
              Dismiss
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ActionRow({ action }: { action: RecommendationAction }) {
  const savings = action.realized_savings_usd ?? action.estimated_savings_usd;
  return (
    <div className="action-row">
      <span className="step-dot" />
      <div className="action-body">
        <div className="action-title">
          <b>{action.title}</b>
          <span>{relativeTime(action.occurred_at)}</span>
        </div>
        <div className="action-detail">
          {leverLabel(action.lever)} · {titleize(action.action_type)} · {titleize(action.status)}
          {savings !== null && savings !== undefined ? ` · ${usd(savings, 0)}` : ""}
        </div>
      </div>
    </div>
  );
}

function useEngineMutation() {
  const { activeProjectId, getToken } = useSession();
  const [busyId, setBusyId] = useState<string | null>(null);

  const updateRecommendation = useCallback(
    async (id: string, status: RecommendationStatus) => {
      setBusyId(id);
      try {
        await api.updateEngineRecommendation(await getToken(), activeProjectId ?? undefined, id, status);
      } finally {
        setBusyId(null);
      }
    },
    [activeProjectId, getToken],
  );

  const updateLever = useCallback(
    async (lever: string, body: { enabled?: boolean; automation_mode?: AutomationMode }) => {
      setBusyId(lever);
      try {
        return await api.updateLever(await getToken(), activeProjectId ?? undefined, lever, body);
      } finally {
        setBusyId(null);
      }
    },
    [activeProjectId, getToken],
  );

  return { busyId, updateRecommendation, updateLever };
}

export function CommandCenterView() {
  return (
    <RequireSession>
      <CommandCenterBody />
    </RequireSession>
  );
}

function CommandCenterBody() {
  const { activeProjectId, getToken } = useSession();
  const { busyId, updateRecommendation } = useEngineMutation();
  const [data, setData] = useState<CommandCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.commandCenter(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const act = async (id: string, status: RecommendationStatus) => {
    try {
      await updateRecommendation(id, status);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (loading || error || !data) {
    return (
      <div className="view">
        <PageHeader
          section="Operate"
          title="Command Center"
          description="Live savings, decision queue, recent engine actions, and the largest waste source."
        />
        <PageState loading={loading} error={error} empty={!data && !loading ? "No command data yet" : undefined} />
      </div>
    );
  }

  const trust = data.live_savings.trust_score === null ? "-" : pct(data.live_savings.trust_score);

  return (
    <div className="view">
      <PageHeader
        section="Operate"
        title="Command Center"
        description="The operating view for what Varsten should cut, prove, and watch right now."
        action={<Link href="/engine/recommendations" className="btn primary">Open Engine</Link>}
      />

      <div className="grid kpi-row">
        <div className="card kpi">
          <div className="label">Spend this month</div>
          <div className="value">{usd(data.live_savings.spend_month, 0)}</div>
          <div className="foot">{compact(data.requests_month)} requests measured</div>
        </div>
        <div className="card kpi">
          <div className="label">Saved this month</div>
          <div className="value">{usd(data.live_savings.saved_month, 0)}</div>
          <div className="foot">gross savings attributed to levers</div>
        </div>
        <div className="card kpi">
          <div className="label">Annual run-rate</div>
          <div className="value">{usd(data.live_savings.annual_run_rate, 0)}</div>
          <div className="foot">based on current monthly savings pace</div>
        </div>
        <div className="card kpi">
          <div className="label">Trust score</div>
          <div className="value">{trust}</div>
          <div className="foot">pricing and metadata coverage</div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head">
            <h3>Decision queue</h3>
            <div className="right"><span className="pill neutral">{data.decision_queue.length} open</span></div>
          </div>
          {data.decision_queue.length === 0 ? (
            <PageState empty="No open recommendations" emptyDetail="The engine has no savings decisions awaiting review." />
          ) : (
            <div className="rec-list">
              {data.decision_queue.slice(0, 6).map((rec) => (
                <RecommendationCard
                  key={rec.id}
                  recommendation={rec}
                  busy={busyId === rec.id}
                  onStatus={act}
                />
              ))}
            </div>
          )}
        </div>

        <div className="grid">
          <div className="card">
            <div className="card-head">
              <h3>Top waste now</h3>
            </div>
            {data.top_waste_now ? (
              <div className="card-pad">
                <RecommendationCard
                  recommendation={data.top_waste_now}
                  busy={busyId === data.top_waste_now.id}
                  onStatus={act}
                />
              </div>
            ) : (
              <PageState empty="No dominant waste source" emptyDetail="Savings opportunities will appear as usage accumulates." />
            )}
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Recent actions</h3>
            </div>
            {data.recent_actions.length === 0 ? (
              <PageState empty="No actions recorded" emptyDetail="Applied recommendations and engine actions will appear here." />
            ) : (
              <div className="action-list">
                {data.recent_actions.slice(0, 8).map((action) => (
                  <ActionRow key={action.id} action={action} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function EngineRecommendationsView() {
  return (
    <RequireSession>
      <EngineRecommendationsBody />
    </RequireSession>
  );
}

function EngineRecommendationsBody() {
  const { activeProjectId, getToken } = useSession();
  const { busyId, updateRecommendation } = useEngineMutation();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.engineRecommendations(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const act = async (id: string, status: RecommendationStatus) => {
    try {
      await updateRecommendation(id, status);
      setItems((current) => current.filter((item) => item.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Engine"
        title="Recommendations"
        description="Ranked savings decisions mapped to Varsten's optimization levers."
      />
      <EngineTabs active="/engine/recommendations" />
      <div className="card">
        <div className="card-head">
          <h3>Open recommendations</h3>
          <div className="right"><span className="pill neutral">{items.length} open</span></div>
        </div>
        {loading || error ? (
          <PageState loading={loading} error={error} />
        ) : items.length === 0 ? (
          <PageState empty="No open recommendations" emptyDetail="The engine will add new opportunities as it detects savings patterns." />
        ) : (
          <div className="rec-list">
            {items.map((rec) => (
              <RecommendationCard
                key={rec.id}
                recommendation={rec}
                busy={busyId === rec.id}
                onStatus={act}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function EngineLeversView() {
  return (
    <RequireSession>
      <EngineLeversBody />
    </RequireSession>
  );
}

function EngineLeversBody() {
  const { activeProjectId, getToken } = useSession();
  const { busyId, updateLever } = useEngineMutation();
  const [items, setItems] = useState<LeverConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.engineLevers(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const totals = useMemo(
    () => ({
      savings: items.reduce((sum, item) => sum + Number(item.savings_to_date_usd ?? 0), 0),
      enabled: items.filter((item) => item.enabled).length,
    }),
    [items],
  );

  const toggle = async (item: LeverConfig) => {
    try {
      const updated = await updateLever(item.lever, { enabled: !item.enabled });
      setItems((current) => current.map((row) => (row.lever === updated.lever ? updated : row)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Engine"
        title="Levers"
        description="The five mechanisms Varsten uses to reduce AI spend without hiding risk."
      />
      <EngineTabs active="/engine/levers" />
      <div className="grid kpi-row">
        <div className="card kpi">
          <div className="label">Enabled levers</div>
          <div className="value">{totals.enabled}/{items.length || 5}</div>
          <div className="foot">active optimization mechanisms</div>
        </div>
        <div className="card kpi">
          <div className="label">Savings to date</div>
          <div className="value">{usd(totals.savings, 0)}</div>
          <div className="foot">attributed across enabled and paused levers</div>
        </div>
        <div className="card kpi">
          <div className="label">Auto mode</div>
          <div className="value">{items.filter((item) => item.automation_mode === "auto").length}</div>
          <div className="foot">levers allowed to act without review</div>
        </div>
        <div className="card kpi">
          <div className="label">Approval mode</div>
          <div className="value">{items.filter((item) => item.automation_mode === "approve").length}</div>
          <div className="foot">human-reviewed optimization paths</div>
        </div>
      </div>
      {loading || error ? (
        <div className="card"><PageState loading={loading} error={error} /></div>
      ) : items.length === 0 ? (
        <div className="card"><PageState empty="No lever configuration" emptyDetail="Seed or ingest usage to initialize engine levers." /></div>
      ) : (
        <div className="lever-grid">
          {items.map((item) => (
            <div className="card lever-card" key={item.id}>
              <div className="lever-top">
                <div>
                  <h3>{leverLabel(item.lever)}</h3>
                  <div className="page-sub">{item.enabled ? "Enabled" : "Paused"} · {titleize(item.automation_mode)} mode</div>
                </div>
                <span className={`pill ${item.enabled ? "green" : "neutral"}`}>{item.enabled ? "On" : "Paused"}</span>
              </div>
              <div className="lever-stats">
                <div>
                  <span>Savings to date</span>
                  <b>{usd(item.savings_to_date_usd, 0)}</b>
                </div>
                <div>
                  <span>Quality delta</span>
                  <b>{signedPct(item.quality_delta_percent)}</b>
                </div>
              </div>
              <button
                className="btn"
                disabled={busyId === item.lever}
                onClick={() => toggle(item)}
                type="button"
              >
                {item.enabled ? "Pause lever" : "Resume lever"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function EngineAutomationView() {
  return (
    <RequireSession>
      <EngineAutomationBody />
    </RequireSession>
  );
}

function EngineAutomationBody() {
  const { activeProjectId, getToken } = useSession();
  const { busyId, updateLever } = useEngineMutation();
  const [items, setItems] = useState<AutomationLever[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.engineAutomation(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const setMode = async (item: AutomationLever, mode: AutomationMode) => {
    if (item.automation_mode === mode) return;
    try {
      await updateLever(item.lever, { automation_mode: mode });
      setItems((current) =>
        current.map((row) => (row.lever === item.lever ? { ...row, automation_mode: mode } : row)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="view">
      <PageHeader
        section="Engine"
        title="Automation"
        description="Control which levers can act automatically and which require approval."
      />
      <EngineTabs active="/engine/automation" />
      <div className="card">
        <div className="card-head">
          <h3>Automation policy</h3>
          <div className="right"><span className="pill neutral">{items.length} levers</span></div>
        </div>
        {loading || error ? (
          <PageState loading={loading} error={error} />
        ) : items.length === 0 ? (
          <PageState empty="No automation policy" emptyDetail="Engine levers will appear here after project setup." />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Lever</th>
                <th>Status</th>
                <th>Risk profile</th>
                <th className="r">Mode</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.lever}>
                  <td>
                    <div className="name">
                      <span className="dot-ic" style={{ background: item.enabled ? "var(--brand)" : "var(--text-faint)" }} />
                      {leverLabel(item.lever)}
                    </div>
                  </td>
                  <td><span className={`pill ${item.enabled ? "green" : "neutral"}`}>{item.enabled ? "Enabled" : "Paused"}</span></td>
                  <td className="muted">{item.risk_profile}</td>
                  <td className="r">
                    <div className="seg" aria-label={`${leverLabel(item.lever)} automation mode`}>
                      <button
                        className={item.automation_mode === "auto" ? "active" : ""}
                        disabled={busyId === item.lever}
                        onClick={() => setMode(item, "auto")}
                        type="button"
                      >
                        Auto
                      </button>
                      <button
                        className={item.automation_mode === "approve" ? "active" : ""}
                        disabled={busyId === item.lever}
                        onClick={() => setMode(item, "approve")}
                        type="button"
                      >
                        Approve
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
