"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useEntitlements } from "@/components/entitlements";
import { useSession } from "@/components/session";
import { LockedNotice } from "@/components/upgradeLock";
import { useProjectResource } from "@/components/useProjectResource";
import { PageState, leverLabel } from "@/components/viewPrimitives";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";
import {
  ENGINE_LEVER_ORDER,
  LEVER_BATCHING,
  LEVER_MODEL_DOWNSHIFT,
  LEVER_PROMPT_COMPRESSION,
  LEVER_SEMANTIC_CACHE,
  LEVER_SMART_ROUTING,
  LEVER_TOKEN_TRIM,
} from "@/lib/levers";
import type {
  ActiveRoute,
  ActiveTrim,
  BatchJob,
  Dashboard,
  LeverConfig,
  PromptCompressionArtifact,
} from "@/lib/types";

type LeverTone = "active" | "waiting" | "setup" | "off" | "locked";

type LeverStatus = {
  detail: string;
  label: string;
  tone: LeverTone;
};

type LeverMeta = {
  description: string;
  iconPath: string;
  requires: string;
};

const LEVER_META: Record<string, LeverMeta> = {
  [LEVER_SEMANTIC_CACHE]: {
    description: "Reuses safe repeated answers instead of calling the model again.",
    requires: "Works when cache storage, semantic lookup, and repeat traffic are available.",
    iconPath: "M6 7c0-1.7 2.7-3 6-3s6 1.3 6 3-2.7 3-6 3-6-1.3-6-3z M6 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7 M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5",
  },
  [LEVER_MODEL_DOWNSHIFT]: {
    description: "Uses a cheaper model when quality checks say it is safe.",
    requires: "Needs enough traffic, a cheaper catalog substitute, and a passing eval.",
    iconPath: "M4 7l8-4 8 4-8 4-8-4z M4 12l8 4 8-4 M4 17l8 4 8-4",
  },
  [LEVER_BATCHING]: {
    description: "Runs non-urgent jobs through provider batch pricing.",
    requires: "Requires callers to submit async work through the Varsten batch API.",
    iconPath: "M5 6h14v4H5z M5 14h14v4H5z M8 10v4 M16 10v4",
  },
  [LEVER_TOKEN_TRIM]: {
    description: "Removes unnecessary context before the model call.",
    requires: "Needs an active trim policy and skips risky requests automatically.",
    iconPath: "M5 5h14v14H5z M8 9h8 M8 12h8 M8 15h5 M3 12h4 M17 12h4 M7 9l-3 3 3 3 M17 9l3 3-3 3",
  },
  [LEVER_SMART_ROUTING]: {
    description: "Routes eligible requests to the lowest-cost model that can handle them.",
    requires: "Needs route evidence, model options, and quality gates before traffic changes.",
    iconPath: "M6 19m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M18 5m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0 M8.5 19H14a3 3 0 0 0 3-3V7.5",
  },
  [LEVER_PROMPT_COMPRESSION]: {
    description: "Uses evaluated shorter prompts when the original prompt matches exactly.",
    requires: "Needs replay samples, a generated rewrite, and a passing shadow eval.",
    iconPath: "M6 4h12v16H6z M9 8h6 M9 11h6 M9 14h4 M3 8l3 3-3 3 M21 8l-3 3 3 3 M10 18h4",
  },
};

function sortedLeverRows(items: LeverConfig[] | null | undefined): LeverConfig[] {
  return [...(items ?? [])].sort((a, b) => {
    const aRank = ENGINE_LEVER_ORDER.indexOf(a.lever as (typeof ENGINE_LEVER_ORDER)[number]);
    const bRank = ENGINE_LEVER_ORDER.indexOf(b.lever as (typeof ENGINE_LEVER_ORDER)[number]);
    return (aRank === -1 ? 99 : aRank) - (bRank === -1 ? 99 : bRank);
  });
}

function LeverIcon({ meta }: { meta: LeverMeta | undefined }) {
  return (
    <div className="automation-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d={meta?.iconPath ?? "M4 12h16 M12 4v16"} />
      </svg>
    </div>
  );
}

function runtimeAvailable(item: LeverConfig): boolean {
  return item.runtime_available !== false;
}

function runtimeReason(item: LeverConfig): string | null {
  return item.runtime_reason ?? null;
}

function routeCount(routes: readonly ActiveRoute[] | null | undefined, lever: string): number {
  return (routes ?? []).filter((route) => route.lever === lever).length;
}

function activeCompressionCount(items: readonly PromptCompressionArtifact[] | null | undefined): number {
  return (items ?? []).filter((item) => item.policy_enabled).length;
}

function totalSavings(items: readonly LeverConfig[]): number {
  return items.reduce((sum, item) => sum + Number(item.savings_to_date_usd || 0), 0);
}

function leverStatus({
  batches,
  compressions,
  item,
  observeOnly,
  routes,
  trims,
}: {
  batches: readonly BatchJob[] | null | undefined;
  compressions: readonly PromptCompressionArtifact[] | null | undefined;
  item: LeverConfig;
  observeOnly: boolean;
  routes: readonly ActiveRoute[] | null | undefined;
  trims: readonly ActiveTrim[] | null | undefined;
}): LeverStatus {
  if (observeOnly) {
    return {
      label: "Observe only",
      tone: "locked",
      detail: "Upgrade to Optimize before Varsten changes production behavior.",
    };
  }
  if (!item.enabled) {
    return {
      label: "Off",
      tone: "off",
      detail: "Varsten will not use this automation for this project.",
    };
  }
  if (!runtimeAvailable(item)) {
    return {
      label: "Needs setup",
      tone: "setup",
      detail: runtimeReason(item) ?? "Finish setup before this automation can run.",
    };
  }

  if (item.lever === LEVER_MODEL_DOWNSHIFT || item.lever === LEVER_SMART_ROUTING) {
    const count = routeCount(routes, item.lever);
    return count > 0
      ? { label: `Running on ${count} ${count === 1 ? "route" : "routes"}`, tone: "active", detail: "Eligible traffic can be routed through checked policies." }
      : { label: "Waiting for eligible traffic", tone: "waiting", detail: "Varsten will use this when quality checks and route evidence are ready." };
  }

  if (item.lever === LEVER_TOKEN_TRIM) {
    const count = trims?.length ?? 0;
    return count > 0
      ? { label: `Running on ${count} ${count === 1 ? "model" : "models"}`, tone: "active", detail: "Eligible requests can be trimmed before forwarding." }
      : { label: "Waiting for high-context traffic", tone: "waiting", detail: "Varsten will trim only where a safe policy exists." };
  }

  if (item.lever === LEVER_PROMPT_COMPRESSION) {
    const active = activeCompressionCount(compressions);
    const prepared = compressions?.length ?? 0;
    if (active > 0) {
      return { label: `Running on ${active} ${active === 1 ? "prompt" : "prompts"}`, tone: "active", detail: "Only exact matches to evaluated prompts are compressed." };
    }
    return prepared > 0
      ? { label: "Prepared, not live", tone: "waiting", detail: "A compressed prompt exists but no live policy is currently active." }
      : { label: "Needs replay samples", tone: "setup", detail: "Capture or add samples before Varsten can prove a shorter prompt." };
  }

  if (item.lever === LEVER_BATCHING) {
    const recent = batches?.filter((job) => job.status === "finalized" || job.status === "completed").length ?? 0;
    return recent > 0
      ? { label: `${recent} recent ${recent === 1 ? "batch" : "batches"}`, tone: "active", detail: "New batch submissions are allowed for non-urgent jobs." }
      : { label: "Ready for batch API", tone: "waiting", detail: "Normal requests are not batched automatically; callers submit batch jobs explicitly." };
  }

  return {
    label: "On",
    tone: "active",
    detail: "Varsten can use this automation on eligible requests.",
  };
}

function Toggle({
  busy,
  disabled,
  enabled,
  label,
  onClick,
  title,
}: {
  busy: boolean;
  disabled: boolean;
  enabled: boolean;
  label: string;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      aria-label={label}
      aria-pressed={enabled}
      className={`lever-toggle${enabled ? " on" : ""}`}
      disabled={busy || disabled}
      onClick={onClick}
      title={title}
      type="button"
    >
      <span />
    </button>
  );
}

function AutomationRow({
  batches,
  busy,
  compressions,
  item,
  observeOnly,
  onToggle,
  routes,
  trims,
}: {
  batches: readonly BatchJob[] | null | undefined;
  busy: boolean;
  compressions: readonly PromptCompressionArtifact[] | null | undefined;
  item: LeverConfig;
  observeOnly: boolean;
  onToggle: (item: LeverConfig) => void;
  routes: readonly ActiveRoute[] | null | undefined;
  trims: readonly ActiveTrim[] | null | undefined;
}) {
  const meta = LEVER_META[item.lever];
  const status = leverStatus({ batches, compressions, item, observeOnly, routes, trims });
  const canToggle = !observeOnly && (runtimeAvailable(item) || item.enabled);
  const title = observeOnly
    ? "Upgrade to Optimize to control production automations."
    : !canToggle
      ? status.detail
      : undefined;

  return (
    <div className="automation-row">
      <div className="automation-main">
        <LeverIcon meta={meta} />
        <div className="automation-copy">
          <div className="automation-title-row">
            <h3>{leverLabel(item.lever)}</h3>
            <span className={`automation-status ${status.tone}`}>{status.label}</span>
          </div>
          <p>{meta?.description ?? "Controls one of Varsten's savings automations."}</p>
          <div className="automation-detail">{status.detail}</div>
          <div className="automation-requires">{meta?.requires}</div>
        </div>
      </div>
      <div className="automation-control">
        <div className="automation-savings">
          <b>{usd(item.savings_to_date_usd, 0)}</b>
          <span>saved</span>
        </div>
        <Toggle
          busy={busy}
          disabled={!canToggle}
          enabled={item.enabled}
          label={`${item.enabled ? "Turn off" : "Turn on"} ${leverLabel(item.lever)}`}
          onClick={() => onToggle(item)}
          title={title}
        />
      </div>
    </div>
  );
}

function AutomationHero({ rows }: { rows: readonly LeverConfig[] }) {
  const enabledCount = rows.filter((row) => row.enabled).length;
  const setupCount = rows.filter((row) => row.runtime_available === false).length;
  return (
    <section className="automation-hero" aria-labelledby="automation-title">
      <div>
        <div className="automation-kicker">Automation</div>
        <h1 id="automation-title">Control how Varsten saves money</h1>
        <p>
          Turn each savings method on or off. Varsten only applies an automation when its
          setup, safety checks, and traffic conditions are actually ready.
        </p>
      </div>
      <div className="automation-hero-stats" aria-label="Automation summary">
        <div><b>{enabledCount}</b><span>on</span></div>
        <div><b>{rows.length - enabledCount}</b><span>off</span></div>
        <div><b>{setupCount}</b><span>need setup</span></div>
        <div><b>{usd(totalSavings(rows), 0)}</b><span>saved</span></div>
      </div>
    </section>
  );
}

function AutomationActivity({
  batches,
  dashboard,
  routes,
  trims,
  compressions,
}: {
  batches: readonly BatchJob[] | null | undefined;
  dashboard: Dashboard | null;
  routes: readonly ActiveRoute[] | null | undefined;
  trims: readonly ActiveTrim[] | null | undefined;
  compressions: readonly PromptCompressionArtifact[] | null | undefined;
}) {
  const actions = dashboard?.recent_actions?.slice(0, 6) ?? [];
  return (
    <details className="automation-details card">
      <summary>
        <span>Activity and live policies</span>
        <b>View details</b>
      </summary>
      <div className="automation-detail-grid">
        <div>
          <h3>Live policies</h3>
          <p>{routeCount(routes, LEVER_MODEL_DOWNSHIFT) + routeCount(routes, LEVER_SMART_ROUTING)} routing</p>
          <p>{trims?.length ?? 0} trim</p>
          <p>{activeCompressionCount(compressions)} compression</p>
          <p>{batches?.length ?? 0} recent batch jobs</p>
        </div>
        <div>
          <h3>Recent activity</h3>
          {actions.length === 0 ? (
            <p>No recent automation activity.</p>
          ) : (
            <ul>
              {actions.map((action) => (
                <li key={action.id}>
                  <span>{action.title}</span>
                  <time>{formatShortDate(action.occurred_at)}</time>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </details>
  );
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function AutomationError({ children }: { children: ReactNode }) {
  return <div className="automation-error">{children}</div>;
}

function AutomationBody() {
  const { activeProjectId, getToken } = useSession();
  const { observeOnly } = useEntitlements();
  const [busyId, setBusyId] = useState<string | null>(null);
  const levers = useProjectResource<LeverConfig[]>(["automationLevers"], api.engineLevers, []);
  const routes = useProjectResource<ActiveRoute[]>(["automationRoutes"], api.engineRoutes, []);
  const trims = useProjectResource<ActiveTrim[]>(["automationTrims"], api.engineTrims, []);
  const batches = useProjectResource<BatchJob[]>(["automationBatches"], api.engineBatches, []);
  const compressions = useProjectResource<PromptCompressionArtifact[]>(["automationCompressions"], api.engineCompressions, []);
  const dashboard = useProjectResource<Dashboard>(["automationActivity"], api.dashboard);

  const rows = useMemo(() => sortedLeverRows(levers.data), [levers.data]);
  const secondaryError = routes.error ?? trims.error ?? batches.error ?? compressions.error ?? dashboard.error;

  const toggleLever = useCallback(
    async (item: LeverConfig) => {
      setBusyId(item.lever);
      levers.setError(null);
      try {
        const updated = await api.updateLever(await getToken(), activeProjectId ?? undefined, item.lever, {
          enabled: !item.enabled,
        });
        levers.setData((current) =>
          (current ?? []).map((row) => (row.lever === item.lever ? { ...row, ...updated } : row)),
        );
      } catch (e) {
        levers.setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyId(null);
      }
    },
    [activeProjectId, getToken, levers],
  );

  return (
    <div className="view automation-view">
      <AutomationHero rows={rows} />
      {observeOnly && (
        <LockedNotice title="Automation is available on Optimize.">
          Free workspaces are observe-only. Varsten can measure traffic, but it will not change production behavior.
        </LockedNotice>
      )}
      {secondaryError ? <AutomationError>{secondaryError}</AutomationError> : null}
      {levers.loading || levers.error ? (
        <div className="card"><PageState loading={levers.loading} error={levers.error} /></div>
      ) : rows.length === 0 ? (
        <div className="card"><PageState empty="No automations configured" emptyDetail="Connect a provider and send traffic to initialize Varsten automations." /></div>
      ) : (
        <section className="card automation-list" aria-label="Money-saving automations">
          <div className="card-head">
            <div>
              <h3>Money-saving automations</h3>
              <p className="sub">Each switch maps to a real project-level runtime control.</p>
            </div>
            <div className="right"><span className="pill neutral">{rows.length} levers</span></div>
          </div>
          {rows.map((item) => (
            <AutomationRow
              key={item.id}
              batches={batches.data}
              busy={busyId === item.lever}
              compressions={compressions.data}
              item={item}
              observeOnly={observeOnly}
              onToggle={toggleLever}
              routes={routes.data}
              trims={trims.data}
            />
          ))}
        </section>
      )}
      <AutomationActivity
        batches={batches.data}
        compressions={compressions.data}
        dashboard={dashboard.data}
        routes={routes.data}
        trims={trims.data}
      />
    </div>
  );
}

export function AutomationView() {
  return (
    <RequireSession>
      <AutomationBody />
    </RequireSession>
  );
}

export function EngineLeversView() {
  return <AutomationView />;
}

export function EngineAutomationView() {
  return <AutomationView />;
}

export function EngineRecommendationsView() {
  return <AutomationView />;
}
