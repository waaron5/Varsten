"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useSession } from "@/components/session";
import { useProjectResource } from "@/components/useProjectResource";
import {
  CollectionState,
  leverLabel,
  PageHeader,
  PageState,
  percent,
  riskClass,
  signedPercent,
  Tabs,
  titleize,
} from "@/components/viewPrimitives";
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

function EngineTabs({ active }: { active: string }) {
  return <Tabs tabs={ENGINE_TABS} active={active} />;
}

function EngineDataCard<T>({
  children,
  countLabel,
  empty,
  emptyDetail,
  error,
  items,
  loading,
  title,
}: {
  children: (items: readonly T[]) => ReactNode;
  countLabel: string;
  empty: string;
  emptyDetail: string;
  error: string | null;
  items: readonly T[] | null | undefined;
  loading: boolean;
  title: string;
}) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        <div className="right"><span className="pill neutral">{items?.length ?? 0} {countLabel}</span></div>
      </div>
      <CollectionState loading={loading} error={error} items={items} empty={empty} emptyDetail={emptyDetail}>
        {children}
      </CollectionState>
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
          <span className="pill neutral">{percent(recommendation.confidence)} confidence</span>
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
  const { busyId, updateRecommendation } = useEngineMutation();
  const { data, loading, error, reload, setError } = useProjectResource<CommandCenter>(api.commandCenter);

  const act = async (id: string, status: RecommendationStatus) => {
    try {
      await updateRecommendation(id, status);
      await reload();
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

  const trust = data.live_savings.trust_score === null ? "-" : percent(data.live_savings.trust_score);

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
  const { busyId, updateRecommendation } = useEngineMutation();
  const {
    data: items,
    loading,
    error,
    setData: setItems,
    setError,
  } = useProjectResource<Recommendation[]>(api.engineRecommendations, []);

  const act = async (id: string, status: RecommendationStatus) => {
    try {
      await updateRecommendation(id, status);
      setItems((current) => (current ?? []).filter((item) => item.id !== id));
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
      <EngineDataCard
        title="Open recommendations"
        countLabel="open"
        loading={loading}
        error={error}
        items={items}
        empty="No open recommendations"
        emptyDetail="The engine will add new opportunities as it detects savings patterns."
      >
        {(rows) => (
          <div className="rec-list">
            {rows.map((rec) => (
              <RecommendationCard
                key={rec.id}
                recommendation={rec}
                busy={busyId === rec.id}
                onStatus={act}
              />
            ))}
          </div>
        )}
      </EngineDataCard>
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
  const { busyId, updateLever } = useEngineMutation();
  const {
    data: items,
    loading,
    error,
    setData: setItems,
    setError,
  } = useProjectResource<LeverConfig[]>(api.engineLevers, []);

  const totals = useMemo(
    () => ({
      savings: (items ?? []).reduce((sum, item) => sum + Number(item.savings_to_date_usd ?? 0), 0),
      enabled: (items ?? []).filter((item) => item.enabled).length,
    }),
    [items],
  );

  const toggle = async (item: LeverConfig) => {
    try {
      const updated = await updateLever(item.lever, { enabled: !item.enabled });
      setItems((current) => (current ?? []).map((row) => (row.lever === updated.lever ? updated : row)));
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
          <div className="value">{totals.enabled}/{items?.length || 5}</div>
          <div className="foot">active optimization mechanisms</div>
        </div>
        <div className="card kpi">
          <div className="label">Savings to date</div>
          <div className="value">{usd(totals.savings, 0)}</div>
          <div className="foot">attributed across enabled and paused levers</div>
        </div>
        <div className="card kpi">
          <div className="label">Auto mode</div>
          <div className="value">{(items ?? []).filter((item) => item.automation_mode === "auto").length}</div>
          <div className="foot">levers allowed to act without review</div>
        </div>
        <div className="card kpi">
          <div className="label">Approval mode</div>
          <div className="value">{(items ?? []).filter((item) => item.automation_mode === "approve").length}</div>
          <div className="foot">human-reviewed optimization paths</div>
        </div>
      </div>
      {loading || error ? (
        <div className="card"><PageState loading={loading} error={error} /></div>
      ) : !items || items.length === 0 ? (
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
                  <b>{signedPercent(item.quality_delta_percent)}</b>
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
  const { busyId, updateLever } = useEngineMutation();
  const {
    data: items,
    loading,
    error,
    setData: setItems,
    setError,
  } = useProjectResource<AutomationLever[]>(api.engineAutomation, []);

  const setMode = async (item: AutomationLever, mode: AutomationMode) => {
    if (item.automation_mode === mode) return;
    try {
      await updateLever(item.lever, { automation_mode: mode });
      setItems((current) =>
        (current ?? []).map((row) => (row.lever === item.lever ? { ...row, automation_mode: mode } : row)),
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
      <EngineDataCard
        title="Automation policy"
        countLabel="levers"
        loading={loading}
        error={error}
        items={items}
        empty="No automation policy"
        emptyDetail="Engine levers will appear here after project setup."
      >
        {(rows) => (
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
              {rows.map((item) => (
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
      </EngineDataCard>
    </div>
  );
}
