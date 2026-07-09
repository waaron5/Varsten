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
import { compact, usd } from "@/lib/format";
import { ENGINE_LEVER_ORDER, LEVER_MODEL_DOWNSHIFT, LEVER_PROMPT_COMPRESSION } from "@/lib/levers";
import type {
  AutomationLever,
  AutomationMode,
  EvalRunSummary,
  LeverConfig,
  Recommendation,
  RecommendationStatus,
} from "@/lib/types";

const ENGINE_TABS = [
  { href: "/engine/levers", label: "Levers" },
  { href: "/engine/automation", label: "Automation" },
  { href: "/engine/recommendations", label: "Recommendations" },
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
    description: "Removes duplicated context, drops low-value retrieval chunks, and rewrites verbose instructions into fewer tokens before the model call.",
    iconPath: "M5 5h14v14H5z M8 9h8 M8 12h8 M8 15h5 M3 12h4 M17 12h4 M7 9l-3 3 3 3 M17 9l3 3-3 3",
    stats: LEVER_STATS,
  },
  [LEVER_PROMPT_COMPRESSION]: {
    description: "Uses an eval-cleared compressed rewrite of a stable system prompt, then substitutes it only on exact prompt-hash matches.",
    iconPath: "M6 4h12v16H6z M9 8h6 M9 11h6 M9 14h4 M3 8l3 3-3 3 M21 8l-3 3 3 3 M10 18h4",
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
    ? "Enable Optimize to apply this recommendation and track savings"
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
      Enable Optimize to apply these recommendations with eval gates and rollback, and to track
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
    <div className="view engine-view">
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
      aria-label={locked ? `${leverLabel(item.lever)} available on Optimize` : `${action} ${leverLabel(item.lever)}`}
      aria-pressed={effectiveOn}
      className={className}
      disabled={busy || locked}
      title={locked ? "Upgrade to Optimize to enable this lever" : undefined}
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
  return (
    <div className="lever-row">
      <div className="lever-row-top">
        <LeverIcon meta={meta} />
        <div className="lever-copy">
          <div className="lever-name">{leverLabel(item.lever)}</div>
        </div>
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
    <div className="view engine-view">
      <PageHeader
        section="Engine"
        title="Levers"
        description="The five mechanisms Varsten uses to reduce AI spend without hiding risk."
      />
      <EngineTabs active="/engine/levers" />
      {observeOnly && (
        <LockedNotice title="Levers change production behavior — available on Optimize.">
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
  const title = locked ? "Upgrade to Optimize to control automation" : undefined;
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
    <div className="view engine-view">
      <PageHeader
        section="Engine"
        title="Automation"
        description="Control which levers can act automatically and which require approval."
      />
      <EngineTabs active="/engine/automation" />
      {observeOnly && (
        <LockedNotice title="Automation runs levers without a human — available on Optimize.">
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
