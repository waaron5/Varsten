"use client";

import type { ReactNode } from "react";
import { useCallback, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useEntitlements } from "@/components/entitlements";
import { useSession } from "@/components/session";
import { EffectiveStatusBadge, LockedNotice } from "@/components/upgradeLock";
import { useProjectResource } from "@/components/useProjectResource";
import {
  CollectionState,
  leverLabel,
  NoticeCard,
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
import { ENGINE_LEVER_ORDER, LEVER_MODEL_DOWNSHIFT } from "@/lib/levers";
import type {
  ActiveRoute,
  ActiveTrim,
  AutomationLever,
  AutomationMode,
  BatchJob,
  EvalRunSummary,
  HoldbackMeasurement,
  LeverConfig,
  Recommendation,
  RecommendationStatus,
  RoutePredicate,
} from "@/lib/types";

const ENGINE_TABS = [
  { href: "/engine/recommendations", label: "Recommendations" },
  { href: "/engine/levers", label: "Levers" },
  { href: "/engine/automation", label: "Automation" },
];

const LEVER_ORDER: readonly string[] = ENGINE_LEVER_ORDER;

type LeverStat = { label: string; value: (item: LeverConfig) => string; emphasis?: boolean };

const LEVER_STATS: LeverStat[] = [
  { label: "Saved this month", value: (item) => usd(item.savings_to_date_usd, 0), emphasis: true },
  { label: "Mode", value: (item) => titleize(item.automation_mode) },
  { label: "Quality delta", value: (item) => signedPercent(item.quality_delta_percent) },
];

const LEVER_META: Record<string, {
  description: string;
  iconPath: string;
  stats: LeverStat[];
}> = {
  smart_routing: {
    description: "Sends each request to the cheapest model that clears the quality bar for that route.",
    iconPath: "M6 19m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M18 5m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M8.5 19H14a3 3 0 0 0 3-3V7.5",
    stats: LEVER_STATS,
  },
  semantic_cache: {
    description: "Reuses an answer when a new request is semantically close to one already served.",
    iconPath: "M6 7c0-1.7 2.7-3 6-3s6 1.3 6 3-2.7 3-6 3-6-1.3-6-3z M6 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7 M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5",
    stats: LEVER_STATS,
  },
  token_trim: {
    description: "Compresses prompts and context before each call without changing the output.",
    iconPath: "M6 6m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M6 18m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M8 7l12 10 M8 17L20 7",
    stats: LEVER_STATS,
  },
  [LEVER_MODEL_DOWNSHIFT]: {
    description: "Systematically moves whole workloads down to a lower-cost tier where evals allow it.",
    iconPath: "M4 7l8-4 8 4-8 4-8-4z M4 12l8 4 8-4 M4 17l8 4 8-4",
    stats: LEVER_STATS,
  },
  batching: {
    description: "Routes non-urgent jobs through batch endpoints to capture bulk pricing.",
    iconPath: "M5 6h14v4H5z M5 14h14v4H5z M8 10v4 M16 10v4",
    stats: LEVER_STATS,
  },
};

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

// Eval verdict -> badge label + pill class. Drives whether Apply is allowed.
const EVAL_VERDICT: Record<string, { label: string; cls: string }> = {
  safe: { label: "Eval passed", cls: "green" },
  needs_human: { label: "Approve manually", cls: "accent" },
  unsafe: { label: "Eval failed", cls: "amber" },
  insufficient_data: { label: "More samples needed", cls: "neutral" },
};

function evalIsRunning(run: EvalRunSummary | null | undefined): boolean {
  return run?.status === "pending" || run?.status === "running";
}

// A gated recommendation may be applied only after a completed run cleared as
// safe or needs_human. The server enforces this too; this keeps the UI honest.
function canApplyRecommendation(rec: Recommendation): boolean {
  if (!rec.gated) return true;
  const run = rec.latest_eval;
  return run?.status === "completed" && (run.verdict === "safe" || run.verdict === "needs_human");
}

function EvalMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <span>{label}</span>
      <b>{value}</b>
    </>
  );
}

function evalQualityDelta(run: EvalRunSummary): string {
  const interval =
    run.score_delta_ci_low !== null && run.score_delta_ci_high !== null
      ? ` (CI ${run.score_delta_ci_low}, ${run.score_delta_ci_high})`
      : "";
  return `${run.score_delta}${interval}`;
}

function EvalVerdictBadge({ run }: { run: EvalRunSummary }) {
  if (!run.verdict) return null;
  const verdict = EVAL_VERDICT[run.verdict] ?? { label: titleize(run.verdict), cls: "neutral" };
  return <span className={`pill ${verdict.cls}`}>{verdict.label}</span>;
}

function EvalEvidence({ run }: { run: EvalRunSummary }) {
  return (
    <div className="eval-evidence">
      <div className="meta-row">
        <EvalVerdictBadge run={run} />
        <span className="pill neutral">candidate {run.candidate_model}</span>
        {run.scorer_type ? <span className="pill neutral">{titleize(run.scorer_type)} scoring</span> : null}
      </div>
      <div className="rec-meta">
        <EvalMetric label="Samples" value={run.sample_count} />
        {run.objective_pass_rate !== null ? <EvalMetric label="Objective parity" value={percent(run.objective_pass_rate, 100)} /> : null}
        {run.score_delta !== null ? <EvalMetric label="Quality delta" value={evalQualityDelta(run)} /> : null}
        {run.cost_delta_usd !== null ? <EvalMetric label="Measured savings" value={`${usd(run.cost_delta_usd, 0)}/mo`} /> : null}
      </div>
      {run.notes ? <p className="eval-note">{run.notes}</p> : null}
    </div>
  );
}

function RecommendationBadges({ recommendation }: { recommendation: Recommendation }) {
  return (
    <div className="meta-row">
      <span className="pill accent">{leverLabel(recommendation.lever)}</span>
      <span className={`pill ${riskClass(recommendation.risk_level)}`}>
        {titleize(recommendation.risk_level)} risk
      </span>
      <span className="pill neutral">{percent(recommendation.confidence)} confidence</span>
      {recommendation.gated ? <span className="pill neutral">Eval gated</span> : null}
    </div>
  );
}

function RecommendationMeta({ recommendation }: { recommendation: Recommendation }) {
  const targetLabel = recommendation.target_type ? titleize(recommendation.target_type) : "Target";
  const target = recommendation.target_key ?? recommendation.related_feature ?? recommendation.related_model ?? "project-wide";
  return (
    <div className="rec-meta">
      <EvalMetric label={targetLabel} value={target} />
      <EvalMetric label="Method" value={titleize(recommendation.measurement_method)} />
      {recommendation.monthly_request_volume !== null ? (
        <EvalMetric label="Requests" value={compact(recommendation.monthly_request_volume)} />
      ) : null}
    </div>
  );
}

function RecommendationEvalStatus({
  gated,
  run,
  running,
}: {
  gated: boolean;
  run: EvalRunSummary | null | undefined;
  running: boolean | undefined;
}) {
  if (run) return <EvalEvidence run={run} />;
  if (running) return <p className="eval-note">Replaying real traffic through the candidate model…</p>;
  if (gated) return <p className="eval-note">This model swap must clear a shadow eval on real traffic before it can be applied.</p>;
  return null;
}

function evaluateButtonLabel(running: boolean | undefined, run: EvalRunSummary | null | undefined): string {
  if (running) return "Evaluating…";
  return run ? "Re-evaluate" : "Evaluate";
}

function RecommendationEvaluateButton({
  busy,
  id,
  onEvaluate,
  run,
  running,
}: {
  busy?: boolean;
  id: string;
  onEvaluate: (id: string) => void;
  run: EvalRunSummary | null | undefined;
  running: boolean | undefined;
}) {
  return (
    <button className="btn" disabled={busy || running} onClick={() => onEvaluate(id)} type="button">
      {evaluateButtonLabel(running, run)}
    </button>
  );
}

function RecommendationStatusButton({
  busy,
  children,
  className = "btn",
  disabled,
  id,
  onStatus,
  status,
  title,
}: {
  busy?: boolean;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  id: string;
  onStatus: (id: string, status: RecommendationStatus) => void;
  status: RecommendationStatus;
  title?: string;
}) {
  return (
    <button className={className} disabled={busy || disabled} title={title} onClick={() => onStatus(id, status)} type="button">
      {children}
    </button>
  );
}

function RecommendationActions({
  busy,
  gated,
  gatedBlocked,
  id,
  locked,
  onEvaluate,
  onStatus,
  run,
  running,
}: {
  busy?: boolean;
  gated: boolean;
  gatedBlocked: boolean;
  id: string;
  locked?: boolean;
  onEvaluate?: (id: string) => void;
  onStatus?: (id: string, status: RecommendationStatus) => void;
  run: EvalRunSummary | null | undefined;
  running: boolean | undefined;
}) {
  if (!onStatus) return null;
  const showEvaluate = gated && onEvaluate;
  const applyTitle = locked
    ? "Enable Performance to apply this recommendation and track savings"
    : gatedBlocked
      ? "Run a shadow eval that clears before applying"
      : undefined;
  return (
    <div className="rec-actions">
      {showEvaluate ? <RecommendationEvaluateButton id={id} busy={busy} run={run} running={running} onEvaluate={onEvaluate} /> : null}
      <RecommendationStatusButton
        className="btn primary"
        disabled={running || gatedBlocked || locked}
        busy={busy}
        id={id}
        onStatus={onStatus}
        status="applied"
        title={applyTitle}
      >
        Apply
      </RecommendationStatusButton>
      <RecommendationStatusButton busy={busy} disabled={running} id={id} onStatus={onStatus} status="dismissed">
        Dismiss
      </RecommendationStatusButton>
    </div>
  );
}

function RecommendationCard({
  recommendation,
  busy,
  evaluating,
  locked,
  onStatus,
  onEvaluate,
}: {
  recommendation: Recommendation;
  busy?: boolean;
  evaluating?: boolean;
  locked?: boolean;
  onStatus?: (id: string, status: RecommendationStatus) => void;
  onEvaluate?: (id: string) => void;
}) {
  const savings = recommendation.estimated_monthly_savings_usd;
  const run = recommendation.latest_eval;
  const gated = Boolean(recommendation.gated);
  const running = Boolean(evaluating || evalIsRunning(run));
  const gatedBlocked = gated && !canApplyRecommendation(recommendation);
  // Measured savings replace the estimate once an eval has produced them.
  const measured = recommendation.measurement_method === "replay_measured";
  return (
    <div className="rec-card">
      <div className="rec-main">
        <RecommendationBadges recommendation={recommendation} />
        <h3>{recommendation.title}</h3>
        <p>{recommendation.rationale ?? recommendation.description}</p>
        <RecommendationMeta recommendation={recommendation} />
        <RecommendationEvalStatus gated={gated} run={run} running={running} />
      </div>
      <div className="rec-side">
        <div className="rec-money">{savings === null ? "Needs pricing" : usd(savings, 0)}</div>
        <div className="rec-sub">{measured ? "measured monthly savings" : "estimated monthly savings"}</div>
        <RecommendationActions
          busy={busy}
          gated={gated}
          gatedBlocked={gatedBlocked}
          id={recommendation.id}
          locked={locked}
          onEvaluate={onEvaluate}
          onStatus={onStatus}
          run={run}
          running={running}
        />
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

// Trigger a shadow eval and poll the recommendations list until the run finishes,
// since it executes off-path in a background worker.
function useEvaluateRecommendation(
  refresh: () => Promise<Recommendation[]>,
) {
  const { getToken } = useSession();
  const [evaluatingId, setEvaluatingId] = useState<string | null>(null);

  const evaluate = useCallback(
    async (id: string) => {
      setEvaluatingId(id);
      try {
        await api.evaluateRecommendation(await getToken(), id);
        for (let i = 0; i < 12; i += 1) {
          await new Promise((resolve) => setTimeout(resolve, 2500));
          const fresh = await refresh();
          const rec = fresh.find((r) => r.id === id);
          const status = rec?.latest_eval?.status;
          if (status === "completed" || status === "failed") break;
        }
      } finally {
        setEvaluatingId(null);
      }
    },
    [getToken, refresh],
  );

  return { evaluatingId, evaluate };
}

export function EngineRecommendationsView() {
  return (
    <RequireSession>
      <EngineRecommendationsBody />
    </RequireSession>
  );
}

function EngineUpgradeBanner({ items }: { items: Recommendation[] | null }) {
  const rows = items ?? [];
  const total = rows.reduce((sum, r) => sum + (r.estimated_monthly_savings_usd ? Number(r.estimated_monthly_savings_usd) : 0), 0);
  const count = rows.length;
  return (
    <NoticeCard badge="Free" title="Observe-only — savings are estimated, not yet captured" style={{ marginBottom: 12 }}>
      {count > 0
        ? `You have ${count} savings ${count === 1 ? "opportunity" : "opportunities"}${total > 0 ? ` worth an estimated ${usd(total, 0)}/mo` : ""}. `
        : "Varsten is measuring your traffic. "}
      Enable Performance to apply these recommendations with eval gates and rollback, and to track
      verified savings. No production behavior is changed until you do.
    </NoticeCard>
  );
}

function EngineRecommendationsBody() {
  const { busyId, updateRecommendation } = useEngineMutation();
  const {
    activeProjectId,
    data: items,
    error,
    getToken,
    loading,
    setData: setItems,
    setError,
  } = useProjectResource<Recommendation[]>(["engineRecommendations"], api.engineRecommendations, []);
  // Shared entitlements: optimistic until known (don't lock on a slow fetch). The
  // backend is the real gate (a free apply returns 403, surfaced as an error).
  const { canApplyRecommendations, loading: entLoading } = useEntitlements();
  const locked = !entLoading && !canApplyRecommendations;

  const refresh = useCallback(async () => {
    const fresh = await api.engineRecommendations(await getToken(), activeProjectId ?? undefined);
    setItems(fresh);
    return fresh;
  }, [activeProjectId, getToken, setItems]);

  const { evaluatingId, evaluate } = useEvaluateRecommendation(refresh);

  const runEvaluate = async (id: string) => {
    try {
      await evaluate(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

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
      {locked && <EngineUpgradeBanner items={items} />}
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
                evaluating={evaluatingId === rec.id}
                locked={locked}
                onStatus={act}
                onEvaluate={runEvaluate}
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

function sortedLeverRows(items: LeverConfig[] | null | undefined): LeverConfig[] {
  return [...(items ?? [])].sort((a, b) => {
    const aRank = LEVER_ORDER.indexOf(a.lever);
    const bRank = LEVER_ORDER.indexOf(b.lever);
    return (aRank === -1 ? 99 : aRank) - (bRank === -1 ? 99 : bRank);
  });
}

function LeverIcon({ meta }: { meta: (typeof LEVER_META)[string] | undefined }) {
  const iconPath = meta?.iconPath || "M4 12h16 M12 4v16";
  return (
    <div className="lever-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d={iconPath} />
      </svg>
    </div>
  );
}

function LeverBadge({ enabled }: { enabled: boolean }) {
  const status = enabled ? "active" : "paused";
  return <span className={`lever-badge ${status}`}>{status}</span>;
}

function LeverActivityGears({ active }: { active: boolean }) {
  return (
    <div className={`lever-gears ${active ? "active" : "paused"}`} aria-hidden="true">
      <svg className="gear gear-large" viewBox="0 0 24 24" fill="none">
        <path d="M12 3v3 M12 18v3 M3 12h3 M18 12h3 M5.6 5.6l2.1 2.1 M16.3 16.3l2.1 2.1 M18.4 5.6l-2.1 2.1 M7.7 16.3l-2.1 2.1" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.8" />
        <circle className="gear-marker" cx="12" cy="5.2" r="1.1" />
      </svg>
      <svg className="gear gear-small" viewBox="0 0 24 24" fill="none">
        <path d="M12 4v2.5 M12 17.5V20 M4 12h2.5 M17.5 12H20 M6.4 6.4l1.8 1.8 M15.8 15.8l1.8 1.8 M17.6 6.4l-1.8 1.8 M8.2 15.8l-1.8 1.8" />
        <circle cx="12" cy="12" r="4.2" />
        <circle cx="12" cy="12" r="1.5" />
        <circle className="gear-marker" cx="12" cy="6" r="0.9" />
      </svg>
    </div>
  );
}

function LeverToggle({
  busy,
  item,
  locked,
  onToggle,
}: {
  busy: boolean;
  item: LeverConfig;
  locked: boolean;
  onToggle: (item: LeverConfig) => void;
}) {
  // Effective state: a locked (observe-only) lever is never shown "on".
  const effectiveOn = !locked && item.enabled;
  const action = effectiveOn ? "Pause" : "Resume";
  const className = effectiveOn ? "lever-toggle on" : "lever-toggle";
  return (
    <button
      aria-label={locked ? `${leverLabel(item.lever)} available on Performance` : `${action} ${leverLabel(item.lever)}`}
      aria-pressed={effectiveOn}
      className={className}
      disabled={busy || locked}
      title={locked ? "Upgrade to Performance to enable this lever" : undefined}
      onClick={() => (locked ? undefined : onToggle(item))}
      type="button"
    />
  );
}

function LeverStats({ item, meta }: { item: LeverConfig; meta: (typeof LEVER_META)[string] | undefined }) {
  const stats = meta?.stats || [];
  return (
    <div className="lever-row-stats">
      {stats.map((stat) => (
        <div key={stat.label}>
          <div className="k">{stat.label}</div>
          <div className={`v ${stat.emphasis ? "emphasis" : ""}`}>{stat.value(item)}</div>
        </div>
      ))}
    </div>
  );
}

function LeverRow({
  busy,
  item,
  observeOnly,
  onToggle,
}: {
  busy: boolean;
  item: LeverConfig;
  observeOnly: boolean;
  onToggle: (item: LeverConfig) => void;
}) {
  const meta = LEVER_META[item.lever];
  const description = meta?.description || "Controls one of Varsten's optimization mechanisms.";
  // Effective, not raw: an observe-only lever is never active regardless of config.
  const effectiveActive = !observeOnly && item.enabled;
  return (
    <div className="lever-row">
      <div className="lever-row-top">
        <LeverIcon meta={meta} />
        <div className="lever-copy">
          <div className="lever-name">{leverLabel(item.lever)}</div>
        </div>
        <LeverActivityGears active={effectiveActive} />
        {observeOnly ? (
          <EffectiveStatusBadge observeOnly active={item.enabled} lockedLabel="Locked on Free" />
        ) : (
          <LeverBadge enabled={item.enabled} />
        )}
        <LeverToggle busy={busy} item={item} locked={observeOnly} onToggle={onToggle} />
      </div>
      <div className="lever-desc">{description}</div>
      <LeverStats item={item} meta={meta} />
    </div>
  );
}

function holdbackLabel(percent: string | null): string {
  if (percent === null) return "-";
  return `${Math.round(Number(percent) * 100)}%`;
}

function RouteSavings({ row }: { row: HoldbackMeasurement }) {
  if (row.measured_savings_usd === null) {
    return <span className="eval-note">gathering arms…</span>;
  }
  const band =
    row.measured_savings_ci_low_usd !== null && row.measured_savings_ci_high_usd !== null
      ? ` (CI ${usd(row.measured_savings_ci_low_usd, 2)}–${usd(row.measured_savings_ci_high_usd, 2)})`
      : "";
  return (
    <span>
      {usd(row.measured_savings_usd, 2)}
      <span className="eval-note">{band}{row.has_signal ? "" : " · provisional"}</span>
    </span>
  );
}

function routeCostLabel(row: HoldbackMeasurement): string {
  if (row.control_avg_cost_usd === null || row.treatment_avg_cost_usd === null) return "-";
  return `${usd(row.control_avg_cost_usd, 4)} → ${usd(row.treatment_avg_cost_usd, 4)}`;
}

function ActiveRoutesEmpty({ error, routes }: { error: string | null; routes: ActiveRoute[] | null | undefined }) {
  if (error && routes && routes.length === 0) {
    return <div className="card"><div className="card-pad"><p className="form-error">{error}</p></div></div>;
  }
  return null;
}

function QuietEmptyState({
  error,
  items,
}: {
  error: string | null;
  items: readonly unknown[] | null | undefined;
}) {
  return error && items && items.length === 0
    ? <div className="card"><div className="card-pad"><p className="form-error">{error}</p></div></div>
    : null;
}

function ActiveRoutesHeader({
  busy,
  onCheckDrift,
}: {
  busy: boolean;
  onCheckDrift: () => void;
}) {
  return (
    <div className="card-head">
      <h3>Active routes</h3>
      <span className="sub">live model-downshift swaps, savings measured against a concurrent holdback</span>
      <button className="btn" disabled={busy} onClick={onCheckDrift} type="button">
        {busy ? "Checking…" : "Run drift check"}
      </button>
    </div>
  );
}

function ActiveRouteRow({
  busy,
  onPause,
  route,
}: {
  busy: boolean;
  onPause: (route: ActiveRoute) => void;
  route: ActiveRoute;
}) {
  return (
    <tr>
      <td>
        <b>{route.incumbent_model}</b> &rarr; {route.candidate_model}
        {route.lever === "smart_routing" ? <span className="pill neutral">predicate</span> : null}
        {route.lever === "smart_routing" && route.predicate ? (
          <span className="eval-note"> {predicateSummary(route.predicate)}</span>
        ) : null}
        {route.activated_at ? <span className="eval-note"> live {relativeTime(route.activated_at)}</span> : null}
      </td>
      <td className="r">{holdbackLabel(route.holdback_percent)}</td>
      <td className="r">{compact(route.control_requests)} / {compact(route.treatment_requests)}</td>
      <td className="r">{routeCostLabel(route)}</td>
      <td className="r"><RouteQuality row={route} /></td>
      <td className="r"><RouteSavings row={route} /></td>
      <td className="r">
        <button className="btn" disabled={busy} onClick={() => onPause(route)} type="button">
          Pause
        </button>
      </td>
    </tr>
  );
}

function predicateSummary(p: RoutePredicate): string {
  const parts: string[] = [];
  if (p.max_prompt_chars != null) parts.push(`≤${compact(p.max_prompt_chars)} chars`);
  if (p.max_completion_tokens != null) parts.push(`≤${compact(p.max_completion_tokens)} out`);
  if (!p.route_when_tools) parts.push("no tools");
  if (!p.route_when_json_schema) parts.push("no JSON");
  return parts.join(" · ");
}

function ActiveRoutesTable({
  busyId,
  onPause,
  routes,
}: {
  busyId: string | null;
  onPause: (route: ActiveRoute) => void;
  routes: ActiveRoute[];
}) {
  return (
    <HoldbackTable firstHeader="Route">
        {routes.map((route) => (
          <ActiveRouteRow key={route.id} route={route} busy={busyId === route.id} onPause={onPause} />
        ))}
    </HoldbackTable>
  );
}

function HoldbackTable({
  children,
  firstHeader,
}: {
  children: ReactNode;
  firstHeader: string;
}) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{firstHeader}</th>
          <th className="r">Holdback</th>
          <th className="r">Control / Treatment</th>
          <th className="r">Cost / req</th>
          <th className="r">Quality</th>
          <th className="r">Measured savings (mo)</th>
          <th />
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function ActiveRoutesCard() {
  const {
    activeProjectId,
    data: routes,
    error,
    getToken,
    loading,
    setData: setRoutes,
    setError,
  } = useProjectResource<ActiveRoute[]>(["engineRoutes"], api.engineRoutes, []);
  const [busyId, setBusyId] = useState<string | null>(null);

  const pause = async (route: ActiveRoute) => {
    setBusyId(route.id);
    setError(null);
    try {
      await api.updateEngineRoute(await getToken(), activeProjectId ?? undefined, route.id, { enabled: false });
      setRoutes((current) => (current ?? []).filter((r) => r.id !== route.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const checkDrift = async () => {
    setBusyId("drift");
    setError(null);
    try {
      const result = await api.checkRouteDrift(await getToken(), activeProjectId ?? undefined);
      // Rolled-back routes are disabled, so refetch to drop them from the list.
      const fresh = await api.engineRoutes(await getToken(), activeProjectId ?? undefined);
      setRoutes(fresh);
      if (result.rolled_back.length > 0) {
        setError(`Rolled back ${result.rolled_back.length} route(s) on quality drift: ${result.rolled_back.map((r) => r.route).join(", ")}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  // Only meaningful once at least one model-downshift swap is live; stay quiet otherwise.
  if (loading || error || !routes || routes.length === 0) {
    return <ActiveRoutesEmpty error={error} routes={routes} />;
  }
  return (
    <div className="card">
      <ActiveRoutesHeader busy={busyId === "drift"} onCheckDrift={checkDrift} />
      {error ? <div className="card-pad"><p className="form-error">{error}</p></div> : null}
      <ActiveRoutesTable routes={routes} busyId={busyId} onPause={pause} />
    </div>
  );
}

function RouteQuality({ row }: { row: HoldbackMeasurement }) {
  if (row.drifted) {
    return <span className="pill amber">drift</span>;
  }
  if (row.treatment_ok_rate === null || row.control_ok_rate === null) {
    return <span className="eval-note">-</span>;
  }
  return (
    <span>
      {percent(row.treatment_ok_rate)}
      <span className="eval-note"> vs {percent(row.control_ok_rate)}</span>
    </span>
  );
}

function ActiveTrimRow({
  busy,
  onPause,
  trim,
}: {
  busy: boolean;
  onPause: (trim: ActiveTrim) => void;
  trim: ActiveTrim;
}) {
  return (
    <tr>
      <td>
        <b>{trim.model}</b> <span className="eval-note">trimmed prompts</span>
        {trim.activated_at ? <span className="eval-note"> · live {relativeTime(trim.activated_at)}</span> : null}
      </td>
      <td className="r">{holdbackLabel(trim.holdback_percent)}</td>
      <td className="r">{compact(trim.control_requests)} / {compact(trim.treatment_requests)}</td>
      <td className="r">{routeCostLabel(trim)}</td>
      <td className="r"><RouteQuality row={trim} /></td>
      <td className="r"><RouteSavings row={trim} /></td>
      <td className="r">
        <button className="btn" disabled={busy} onClick={() => onPause(trim)} type="button">
          Pause
        </button>
      </td>
    </tr>
  );
}

function ActiveTrimsCard() {
  const {
    activeProjectId,
    data: trims,
    error,
    getToken,
    loading,
    setData: setTrims,
    setError,
  } = useProjectResource<ActiveTrim[]>(["engineTrims"], api.engineTrims, []);
  const [busyId, setBusyId] = useState<string | null>(null);

  const pause = async (trim: ActiveTrim) => {
    setBusyId(trim.id);
    setError(null);
    try {
      await api.updateEngineTrim(await getToken(), activeProjectId ?? undefined, trim.id, { enabled: false });
      setTrims((current) => (current ?? []).filter((t) => t.id !== trim.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  // Quiet until at least one trim policy is live.
  if (loading || error || !trims || trims.length === 0) {
    return <QuietEmptyState error={error} items={trims} />;
  }
  return (
    <div className="card">
      <div className="card-head">
        <h3>Active trims</h3>
        <span className="sub">live token-trim policies, savings measured against an untrimmed holdback</span>
      </div>
      {error ? <div className="card-pad"><p className="form-error">{error}</p></div> : null}
      <HoldbackTable firstHeader="Model">
          {trims.map((trim) => (
            <ActiveTrimRow key={trim.id} trim={trim} busy={busyId === trim.id} onPause={pause} />
          ))}
      </HoldbackTable>
    </div>
  );
}

const BATCH_STATUS_CLASS: Record<string, string> = {
  finalized: "green",
  completed: "green",
  failed: "amber",
  expired: "amber",
  cancelled: "neutral",
};

const BATCH_HEADERS = ["Submitted", "Status", "Requests", "Tokens in / out", "Naive cost", "Saved"];

function BatchStatusPill({ status }: { status: string }) {
  const cls = BATCH_STATUS_CLASS[status] ?? "accent";
  return <span className={`pill ${cls}`}>{titleize(status)}</span>;
}

function BatchJobRow({ job }: { job: BatchJob }) {
  return (
    <tr>
      <td>{relativeTime(job.submitted_at ?? job.created_at)}</td>
      <td><BatchStatusPill status={job.status} /></td>
      <td className="r">{compact(job.request_count)}</td>
      <td className="r">{compact(job.input_tokens)} / {compact(job.output_tokens)}</td>
      <td className="r">{job.naive_cost_usd === null ? "-" : usd(job.naive_cost_usd, 2)}</td>
      <td className="r emphasis">{job.saved_usd === null ? "-" : usd(job.saved_usd, 2)}</td>
    </tr>
  );
}

function BatchJobsTable({ jobs }: { jobs: BatchJob[] }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          {BATCH_HEADERS.map((header, index) => (
            <th key={header} className={index > 1 ? "r" : undefined}>{header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => <BatchJobRow key={job.id} job={job} />)}
      </tbody>
    </table>
  );
}

function BatchJobsCard() {
  const { data: jobs, error, loading } = useProjectResource<BatchJob[]>(["engineBatches"], api.engineBatches, []);

  // Quiet until the client has run at least one batch.
  if (loading || error || !jobs || jobs.length === 0) {
    return <QuietEmptyState error={error} items={jobs} />;
  }
  return (
    <div className="card">
      <div className="card-head">
        <h3>Batch jobs</h3>
        <span className="sub">async batch runs, ~50% off measured against synchronous pricing</span>
      </div>
      <BatchJobsTable jobs={jobs} />
    </div>
  );
}

function EngineLeversBody() {
  const { busyId, updateLever } = useEngineMutation();
  const { observeOnly } = useEntitlements();
  const {
    data: items,
    loading,
    error,
    setData: setItems,
    setError,
  } = useProjectResource<LeverConfig[]>(["engineLevers"], api.engineLevers, []);

  const toggle = async (item: LeverConfig) => {
    try {
      const updated = await updateLever(item.lever, { enabled: !item.enabled });
      setItems((current) => (current ?? []).map((row) => (row.lever === updated.lever ? updated : row)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const rows = sortedLeverRows(items);

  return (
    <div className="view">
      <PageHeader
        section="Engine"
        title="Levers"
        description="The five mechanisms Varsten uses to reduce AI spend without hiding risk."
      />
      <EngineTabs active="/engine/levers" />
      {observeOnly && (
        <LockedNotice title="Levers change production behavior — available on Performance.">
          On Free, Varsten observes your traffic only. Upgrade to turn levers on and capture savings.
        </LockedNotice>
      )}
      {loading || error ? (
        <div className="card"><PageState loading={loading} error={error} /></div>
      ) : !items || items.length === 0 ? (
        <div className="card"><PageState empty="No lever configuration" emptyDetail="Seed or ingest usage to initialize engine levers." /></div>
      ) : (
        <div className="card lever-list-card">
          {rows.map((item) => (
            <LeverRow key={item.id} item={item} busy={busyId === item.lever} observeOnly={observeOnly} onToggle={toggle} />
          ))}
        </div>
      )}
      <ActiveRoutesCard />
      <ActiveTrimsCard />
      <BatchJobsCard />
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

function AutomationModeControl({
  busy,
  item,
  locked,
  onMode,
}: {
  busy: boolean;
  item: AutomationLever;
  locked: boolean;
  onMode: (item: AutomationLever, mode: AutomationMode) => void;
}) {
  const title = locked ? "Upgrade to Performance to control automation" : undefined;
  return (
    <div className="seg" aria-label={`${leverLabel(item.lever)} automation mode`}>
      <button
        className={!locked && item.automation_mode === "auto" ? "active" : ""}
        disabled={busy || locked}
        title={title}
        onClick={() => (locked ? undefined : onMode(item, "auto"))}
        type="button"
      >
        Auto
      </button>
      <button
        className={!locked && item.automation_mode === "approve" ? "active" : ""}
        disabled={busy || locked}
        title={title}
        onClick={() => (locked ? undefined : onMode(item, "approve"))}
        type="button"
      >
        Approve
      </button>
    </div>
  );
}

function AutomationRow({
  busy,
  item,
  observeOnly,
  onMode,
}: {
  busy: boolean;
  item: AutomationLever;
  observeOnly: boolean;
  onMode: (item: AutomationLever, mode: AutomationMode) => void;
}) {
  const effectiveEnabled = !observeOnly && item.enabled;
  return (
    <tr>
      <td>
        <div className="name">
          <span className="dot-ic" style={{ background: effectiveEnabled ? "var(--brand)" : "var(--text-faint)" }} />
          {leverLabel(item.lever)}
        </div>
      </td>
      <td>
        {observeOnly ? (
          <EffectiveStatusBadge observeOnly active={item.enabled} lockedLabel="Locked on Free" />
        ) : (
          <span className={`pill ${item.enabled ? "green" : "neutral"}`}>{item.enabled ? "Enabled" : "Paused"}</span>
        )}
      </td>
      <td className="muted">{item.risk_profile}</td>
      <td className="r"><AutomationModeControl busy={busy} item={item} locked={observeOnly} onMode={onMode} /></td>
    </tr>
  );
}

function AutomationTable({
  busyId,
  observeOnly,
  onMode,
  rows,
}: {
  busyId: string | null;
  observeOnly: boolean;
  onMode: (item: AutomationLever, mode: AutomationMode) => void;
  rows: readonly AutomationLever[];
}) {
  return (
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
          <AutomationRow key={item.lever} item={item} busy={busyId === item.lever} observeOnly={observeOnly} onMode={onMode} />
        ))}
      </tbody>
    </table>
  );
}

function EngineAutomationBody() {
  const { busyId, updateLever } = useEngineMutation();
  const { observeOnly } = useEntitlements();
  const {
    data: items,
    loading,
    error,
    setData: setItems,
    setError,
  } = useProjectResource<AutomationLever[]>(["engineAutomation"], api.engineAutomation, []);

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
      {observeOnly && (
        <LockedNotice title="Automation runs levers without a human — available on Performance.">
          Free is observe-only. Upgrade to let Varsten auto-apply or require approval per lever.
        </LockedNotice>
      )}
      <EngineDataCard
        title="Automation policy"
        countLabel="levers"
        loading={loading}
        error={error}
        items={items}
        empty="No automation policy"
        emptyDetail="Engine levers will appear here after project setup."
      >
        {(rows) => <AutomationTable rows={rows} busyId={busyId} observeOnly={observeOnly} onMode={setMode} />}
      </EngineDataCard>
    </div>
  );
}
