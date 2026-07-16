"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import { useTimedPolling } from "@/components/useTimedPolling";
import { useSession } from "@/components/session";
import { ApiError, api } from "@/lib/api";
import { currentOnboardingIntent } from "@/lib/onboardingIntent";
import {
  DOCS_HREF,
  EXAMPLE_MODELS,
  INTEGRATION_LANGUAGES,
  INTEGRATION_PATHS,
  PROVIDER_LABELS,
  PROXY_BASE,
  SDK_FAILOPEN_TEST,
  SIDECAR_PLANNED,
  buildRecipe,
  integrationPath,
  sdkSupportsLanguage,
  type IntegrationLanguageId,
  type IntegrationPath,
  type IntegrationPathId,
  type IntegrationProviderId,
  type RecipeBlock,
} from "@/lib/integrationSnippets";
import type { ApiKeyCreated, OnboardingIntegration, OnboardingStatus } from "@/lib/types";

const SETUP_CALL_HREF = "mailto:mail@varsten.ai?subject=Varsten%20setup%20call";
type ProviderId = IntegrationProviderId;
type LanguageId = IntegrationLanguageId;
type ProviderConnectionStatus = OnboardingStatus["provider_connections"][number];

const PROVIDER_KEY_PLACEHOLDERS: Record<ProviderId, string> = {
  openai: "sk-...",
  anthropic: "sk-ant-...",
  gemini: "AIza...",
};

const CHECK_ICON = "M20 6L9 17l-5-5";

function OnbIcon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function languageStorageKey(projectId: string): string {
  return `varsten:onboarding-language:${projectId}`;
}

function storedLanguage(projectId: string): LanguageId | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(languageStorageKey(projectId));
    return INTEGRATION_LANGUAGES.some((l) => l.id === value) ? (value as LanguageId) : null;
  } catch {
    return null;
  }
}

// The language choice is cosmetic (it only parametrizes the rendered recipe), so
// it lives in localStorage rather than the backend selection. Exposed through a
// tiny external store so SSR paints the default and the client restores the
// stored choice without a hydration mismatch.
const languageListeners = new Set<() => void>();
// In-memory overlay so the choice still applies this session even when
// localStorage is unavailable (private mode, blocked storage).
const languageMemory = new Map<string, LanguageId>();

function useStoredLanguage(projectId: string): [LanguageId, (next: LanguageId) => void] {
  const subscribe = useCallback((onChange: () => void) => {
    languageListeners.add(onChange);
    return () => languageListeners.delete(onChange);
  }, []);
  const language = useSyncExternalStore<LanguageId>(
    subscribe,
    () => languageMemory.get(projectId) ?? storedLanguage(projectId) ?? "node",
    () => "node",
  );
  const setLanguage = useCallback(
    (next: LanguageId) => {
      languageMemory.set(projectId, next);
      try {
        window.localStorage.setItem(languageStorageKey(projectId), next);
      } catch {
        // Non-fatal; without storage the choice resets next visit.
      }
      languageListeners.forEach((onChange) => onChange());
    },
    [projectId],
  );
  return [language, setLanguage];
}

function defaultPathForIntent(): IntegrationPathId {
  // Observe intent = the 60-second base-URL "try". Trial / unknown = the
  // production-safe SDK, which is also the recommended path.
  return currentOnboardingIntent() === "observe" ? "base_url" : "sdk";
}

export function OnboardingView() {
  return (
    <RequireSession>
      <OnboardingBody />
    </RequireSession>
  );
}

function OnboardingBody() {
  const router = useRouter();
  const { activeProjectId, getToken } = useSession();
  const { data, loading, error, reload } = useProjectResource<OnboardingStatus>(["onboardingStatus"], api.onboardingStatus);
  const [completionError, setCompletionError] = useState<string | null>(null);

  const canComplete = data?.can_complete ?? false;

  // Poll while verification is incomplete. This keeps watching through mismatch
  // states, such as base-URL traffic arriving when the SDK path was selected.
  useTimedPolling(Boolean(data && !canComplete), 4000, reload);

  const recordEvent = useCallback(
    async (event: "snippet_viewed" | "dashboard_entered") => {
      try {
        await api.onboardingEvent(await getToken(), activeProjectId ?? undefined, event);
      } catch {
        // Checklist events are best-effort; never block the funnel on them.
      }
    },
    [activeProjectId, getToken],
  );

  const finish = useCallback(async () => {
    setCompletionError(null);
    try {
      await recordEvent("dashboard_entered");
      await api.completeOnboarding(await getToken(), activeProjectId ?? undefined);
      router.push("/dashboard");
    } catch {
      setCompletionError("Setup is not verified yet. Send the first request shown here, then try again.");
    }
  }, [activeProjectId, getToken, recordEvent, router]);

  if (loading && !data) {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
        <div className="empty">
          <div className="spinner" />
          <div className="es">Loading your setup…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="view">
        <div className="empty">
          <div className="et">Could not load onboarding</div>
          <div className="es">{error ?? "Unknown error"}</div>
          <button className="btn primary" onClick={() => void reload()}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <OnboardingWizard
      completionError={completionError}
      onFinish={() => void finish()}
      onLeave={() => router.push("/dashboard")}
      onReload={() => void reload()}
      onSnippetViewed={() => void recordEvent("snippet_viewed").then(() => reload())}
      status={data}
    />
  );
}

// --- wizard step model -------------------------------------------------------

type StepKey = "stack" | "keys" | "verify";

interface StepMeta {
  key: StepKey;
  label: string;
  done: boolean;
}

function checklistComplete(status: OnboardingStatus, key: string): boolean {
  return status.checklist.some((item) => item.key === key && item.complete);
}

function buildSteps(status: OnboardingStatus, path: IntegrationPath): StepMeta[] {
  const keysDone =
    checklistComplete(status, "has_api_key") &&
    (!path.requiresProviderConnection || checklistComplete(status, "has_provider_connection"));
  return [
    { key: "stack", label: "Stack", done: status.selection_saved },
    { key: "keys", label: "Keys", done: keysDone },
    { key: "verify", label: "Verify", done: status.can_complete },
  ];
}

function stackSub(status: OnboardingStatus): string {
  return status.observe_only
    ? "Varsten measures your AI spend and surfaces where it can be cut. Pick your provider and how traffic reaches us — nothing changes in production until you turn on optimization."
    : "Varsten cuts your AI spend and proves it. Pick your provider and how traffic reaches us — one exact recipe is generated for you, and you can move up the ladder later without re-integrating.";
}

function stepHead(key: StepKey, status: OnboardingStatus, path: IntegrationPath, provider: ProviderId): { title: string; sub: string } {
  switch (key) {
    case "stack":
      return { title: "Connect your stack", sub: stackSub(status) };
    case "keys":
      return path.requiresProviderConnection
        ? {
            title: "Add your keys",
            sub: `Your Varsten key identifies this project's traffic. Your ${PROVIDER_LABELS[provider]} key is encrypted and used only to reach the provider on your behalf.`,
          }
        : {
            title: "Create your Varsten key",
            sub: "One key. It authorizes usage records for this project — no provider key needed.",
          };
    case "verify":
      switch (path.method) {
        case "sdk":
          return {
            title: "Install, then send a request",
            sub: "Drop this recipe into your app and run it. Setup verifies the moment your first request lands.",
          };
        case "base_url":
          return {
            title: "Point your client at Varsten",
            sub: "Swap the base URL and run any normal request. Setup verifies the moment traffic lands.",
          };
        default:
          return {
            title: "Send your first usage record",
            sub: "POST one usage record after an LLM call. Setup verifies the moment it lands.",
          };
      }
  }
}

// --- top progress stepper ----------------------------------------------------

function stepStatus(done: boolean, active: boolean): string {
  if (done) return "completed";
  return active ? "current" : "upcoming";
}

function WizardStepper({ steps, activeIndex }: { steps: StepMeta[]; activeIndex: number }) {
  return (
    <ol className="onb-steps" aria-label="Setup progress">
      {steps.map((step, i) => (
        <li
          key={step.key}
          className={`onb-step${step.done ? " done" : ""}${i === activeIndex ? " active" : ""}`}
          aria-current={i === activeIndex ? "step" : undefined}
        >
          <span className="onb-step-num mono">
            {step.done ? (
              <span className="onb-step-check"><OnbIcon path={CHECK_ICON} /></span>
            ) : (
              `0${i + 1}`
            )}
          </span>
          <span className="onb-step-label">
            {step.label}
            <span className="onb-sr-only"> — {stepStatus(step.done, i === activeIndex)}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

// --- shared bottom navigation ------------------------------------------------

interface PrimaryAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

function StepFooter({
  onBack,
  primary,
  secondary,
}: {
  onBack: (() => void) | null;
  primary: PrimaryAction;
  secondary?: ReactNode;
}) {
  return (
    <div className="onb-foot">
      <div className="onb-nav">
        {onBack ? (
          <button className="btn onb-nav-back" onClick={onBack}>Back</button>
        ) : null}
        <button className="btn primary onb-nav-primary" onClick={primary.onClick} disabled={primary.disabled}>
          {primary.label}
        </button>
      </div>
      {secondary ? <div className="onb-secondary">{secondary}</div> : null}
    </div>
  );
}

function resolveOpenKey(manualKey: StepKey | null, steps: StepMeta[]): StepKey {
  if (manualKey && steps.some((s) => s.key === manualKey)) return manualKey;
  const firstIncomplete = steps.find((s) => !s.done);
  return firstIncomplete?.key ?? steps[steps.length - 1].key;
}

function useWizardNavigation(steps: StepMeta[]) {
  // manualKey is the user's explicit position in the wizard (set by Back /
  // Continue). Whenever it no longer names a step in the current list this falls
  // through to the first incomplete step, computed at render time rather than
  // corrected in an effect.
  const [manualKey, setManualKey] = useState<StepKey | null>(null);
  const openKey = useMemo(() => resolveOpenKey(manualKey, steps), [manualKey, steps]);
  const currentIndex = steps.findIndex((s) => s.key === openKey);
  const goNext = useCallback(() => {
    setManualKey(steps[Math.min(currentIndex + 1, steps.length - 1)].key);
  }, [steps, currentIndex]);
  const goBack = currentIndex > 0 ? () => setManualKey(steps[currentIndex - 1].key) : null;
  return { currentIndex, goBack, goNext, openKey, setManualKey };
}

// --- selection state (path + provider on the backend, language local) ---------

function providerForPath(pathId: IntegrationPathId, provider: ProviderId): ProviderId | null {
  return pathId === "metadata" ? null : provider;
}

function useOnboardingSelection(status: OnboardingStatus, onReload: () => void) {
  const { activeProjectId, getToken } = useSession();
  const [draftPathId, setDraftPathId] = useState<IntegrationPathId | null>(null);
  const [draftProvider, setDraftProvider] = useState<ProviderId | null>(null);
  const [language, setLanguage] = useStoredLanguage(status.project_id);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionErr, setSelectionErr] = useState<string | null>(null);

  const pathId = draftPathId ?? status.selected_path ?? defaultPathForIntent();
  const selectedProvider = draftProvider ?? status.selected_provider ?? "openai";
  // Invariant: the fail-open SDK ships for TypeScript today, so the SDK path
  // always renders the TypeScript recipe regardless of a stale language choice.
  const effectiveLanguage: LanguageId = pathId === "sdk" && !sdkSupportsLanguage(language) ? "node" : language;
  const path = integrationPath(pathId);

  const saveSelection = useCallback(
    async (nextPath: IntegrationPathId, provider: ProviderId | null): Promise<boolean> => {
      setSelectionBusy(true);
      setSelectionErr(null);
      try {
        await api.saveOnboardingSelection(await getToken(), activeProjectId ?? undefined, { path: nextPath, provider });
        onReload();
        return true;
      } catch (e) {
        setSelectionErr(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setSelectionBusy(false);
      }
    },
    [activeProjectId, getToken, onReload],
  );

  return {
    effectiveLanguage,
    path,
    pathId,
    saveSelection,
    selectedProvider,
    selectionBusy,
    selectionErr,
    setDraftPathId,
    setDraftProvider,
    setLanguage,
  };
}

function OnboardingWizard({
  completionError,
  status,
  onReload,
  onFinish,
  onLeave,
  onSnippetViewed,
}: {
  completionError: string | null;
  status: OnboardingStatus;
  onReload: () => void;
  onFinish: () => void;
  onLeave: () => void;
  onSnippetViewed: () => void | Promise<void>;
}) {
  const selection = useOnboardingSelection(status, onReload);
  const { effectiveLanguage, path, pathId, saveSelection, selectedProvider, selectionBusy, selectionErr, setDraftPathId, setDraftProvider, setLanguage } = selection;
  const steps = useMemo(() => buildSteps(status, path), [status, path]);
  const { currentIndex, goBack, goNext, openKey, setManualKey } = useWizardNavigation(steps);
  // The plaintext vk_ key lives only in this component's memory for the session,
  // so the verify step can render a copy-paste-complete env block. Never persisted.
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);

  const selectPath = useCallback(
    async (id: IntegrationPathId) => {
      setDraftPathId(id);
      setManualKey("stack");
      await saveSelection(id, providerForPath(id, selectedProvider));
    },
    [saveSelection, selectedProvider, setDraftPathId, setManualKey],
  );

  const selectProvider = useCallback(
    async (provider: ProviderId) => {
      setDraftProvider(provider);
      await saveSelection(pathId, providerForPath(pathId, provider));
    },
    [pathId, saveSelection, setDraftProvider],
  );

  const selectLanguage = useCallback(
    (id: LanguageId) => {
      setLanguage(id);
      // Picking a stack the SDK does not ship for yet moves the selection to the
      // gateway URL — the honest equivalent — instead of leaving a dead recipe.
      if (pathId === "sdk" && !sdkSupportsLanguage(id)) {
        void selectPath("base_url");
      }
    },
    [pathId, selectPath, setLanguage],
  );

  const continueFromStack = useCallback(async () => {
    if (!status.selection_saved || status.selected_path !== pathId || status.selected_provider !== providerForPath(pathId, selectedProvider)) {
      const saved = await saveSelection(pathId, providerForPath(pathId, selectedProvider));
      if (!saved) return;
    }
    goNext();
  }, [goNext, pathId, saveSelection, selectedProvider, status.selected_path, status.selected_provider, status.selection_saved]);

  const head = stepHead(openKey, status, path, selectedProvider);

  return (
    <div className="view">
      <div className="onb">
        <div className="onb-meta mono">
          <span>SETUP · {status.project_name.toUpperCase()}</span>
          <span>{`0${currentIndex + 1} — 0${steps.length}`}</span>
        </div>

        <WizardStepper steps={steps} activeIndex={currentIndex} />

        <div className="onb-head">
          <h2 className="onb-title">{head.title}</h2>
          <p className="onb-sub">{head.sub}</p>
        </div>

        <div className="onb-body">
          {openKey === "stack" ? (
            <StackStep
              busy={selectionBusy}
              error={selectionErr}
              language={effectiveLanguage}
              onContinue={() => void continueFromStack()}
              onSelectLanguage={selectLanguage}
              onSelectPath={(id) => void selectPath(id)}
              onSelectProvider={(id) => void selectProvider(id)}
              pathId={pathId}
              provider={selectedProvider}
            />
          ) : null}
          {openKey === "keys" ? (
            <KeysStep
              createdKey={createdKey}
              onBack={goBack}
              onChanged={onReload}
              onContinue={goNext}
              onKeyCreated={setCreatedKey}
              onUseMetadata={() => void selectPath("metadata")}
              path={path}
              provider={selectedProvider}
              status={status}
            />
          ) : null}
          {openKey === "verify" ? (
            <VerifyStep
              completionError={completionError}
              createdKey={createdKey}
              language={effectiveLanguage}
              onBack={goBack}
              onFinish={onFinish}
              onLeave={onLeave}
              onSnippetViewed={onSnippetViewed}
              path={path}
              provider={selectedProvider}
              status={status}
            />
          ) : null}
        </div>

        <div className="onb-help">
          <a href={DOCS_HREF} target="_blank" rel="noreferrer">View docs</a>
          <a href={SETUP_CALL_HREF}>Book a setup call</a>
        </div>
      </div>
    </div>
  );
}

// --- step 1: stack -------------------------------------------------------------

type TagTone = "pos" | "neg" | "neutral";
type TagMeta = { label: string; tone: TagTone };

function Tag({ label, tone }: TagMeta) {
  return <span className={`onb-tag${tone === "pos" ? " pos" : tone === "neg" ? " neg" : ""}`}>{label}</span>;
}

const FAIL_OPEN_TAGS: Record<IntegrationPath["failOpen"], TagMeta> = {
  yes: { label: "Fail-open", tone: "pos" },
  no: { label: "Not fail-open", tone: "neg" },
  "n/a": { label: "Nothing inline", tone: "pos" },
};

function pathTags(path: IntegrationPath): TagMeta[] {
  return [
    FAIL_OPEN_TAGS[path.failOpen],
    path.seesContent ? { label: "Sees content", tone: "neutral" } : { label: "Metadata only", tone: "pos" },
    { label: path.needsProviderKey ? "Provider key" : "No provider key", tone: "neutral" },
    { label: path.unlocksOptimize ? "Can optimize" : "Measure only", tone: "neutral" },
  ];
}

function SegRow<T extends string>({
  label,
  options,
  value,
  onSelect,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onSelect: (id: T) => void;
}) {
  return (
    <div className="onb-field">
      <div className="onb-field-label mono">{label}</div>
      <div className="onb-seg" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={option.id === value}
            className={`onb-seg-btn${option.id === value ? " active" : ""}`}
            onClick={() => onSelect(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function StackStep({
  busy,
  error,
  language,
  onContinue,
  onSelectLanguage,
  onSelectPath,
  onSelectProvider,
  pathId,
  provider,
}: {
  busy: boolean;
  error: string | null;
  language: LanguageId;
  onContinue: () => void;
  onSelectLanguage: (id: LanguageId) => void;
  onSelectPath: (id: IntegrationPathId) => void;
  onSelectProvider: (id: ProviderId) => void;
  pathId: IntegrationPathId;
  provider: ProviderId;
}) {
  const sdkLocked = !sdkSupportsLanguage(language);
  return (
    <>
      <SegRow
        label="PROVIDER"
        options={(Object.keys(PROVIDER_LABELS) as ProviderId[]).map((id) => ({ id, label: PROVIDER_LABELS[id] }))}
        value={provider}
        onSelect={onSelectProvider}
      />
      <SegRow label="LANGUAGE" options={INTEGRATION_LANGUAGES} value={language} onSelect={onSelectLanguage} />

      <div className="onb-field">
        <div className="onb-field-label mono">INTEGRATION PATH</div>
        <div className="onb-options">
          {INTEGRATION_PATHS.map((p) => {
            const locked = p.id === "sdk" && sdkLocked;
            return (
              <PathOption
                key={p.id}
                active={p.id === pathId}
                locked={locked}
                onSelect={() => onSelectPath(p.id)}
                path={p}
              />
            );
          })}
          <SidecarPlannedCard />
        </div>
      </div>

      {error ? <div className="onb-note neg">{error}</div> : null}
      <StepFooter onBack={null} primary={{ label: busy ? "Saving…" : "Continue", onClick: onContinue, disabled: busy }} />
    </>
  );
}

function PathOption({
  active,
  locked,
  onSelect,
  path,
}: {
  active: boolean;
  locked: boolean;
  onSelect: () => void;
  path: IntegrationPath;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`onb-option${active ? " active" : ""}${locked ? " locked" : ""}`}
      aria-pressed={active}
      disabled={locked}
    >
      <span className="onb-option-main">
        <span className="onb-option-name">
          {path.name}
          <span className="onb-option-bestfor">Best for {path.bestFor.toLowerCase()}</span>
          {path.recommended ? <span className="onb-flag mono">RECOMMENDED</span> : null}
        </span>
        <span className="onb-option-tagline">
          {locked
            ? "TypeScript today — an SDK for your stack is planned. Use the gateway URL or metadata ingestion meanwhile."
            : path.tagline}
        </span>
        <span className="onb-tags">
          {pathTags(path).map((tag) => <Tag key={tag.label} label={tag.label} tone={tag.tone} />)}
        </span>
      </span>
      <span className="onb-radio" aria-hidden="true" />
    </button>
  );
}

function SidecarPlannedCard() {
  return (
    <div className="onb-option planned" aria-disabled="true">
      <span className="onb-option-main">
        <span className="onb-option-name">
          {SIDECAR_PLANNED.name}
          <span className="onb-option-bestfor">Best for {SIDECAR_PLANNED.bestFor.toLowerCase()}</span>
          <span className="onb-flag mono muted">PLANNED</span>
        </span>
        <span className="onb-option-tagline">{SIDECAR_PLANNED.tagline}</span>
        <span className="onb-option-tagline">
          Not available yet. <a className="onb-inline-link" href={SIDECAR_PLANNED.contactHref}>Talk to us</a> if this is
          your required deployment model — it moves it up the roadmap.
        </span>
      </span>
    </div>
  );
}

// --- step 2: keys ----------------------------------------------------------------

function CopyButton({ value, label = "Copy", onCopy }: { value: string; label?: string; onCopy?: () => void | Promise<void> }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="onb-copy"
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable; the value is selectable in the block */
        }
        void onCopy?.();
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

function CodeBlock({
  block,
  onSnippetViewed,
}: {
  block: RecipeBlock;
  onSnippetViewed?: () => void | Promise<void>;
}) {
  return (
    <div className="onb-code">
      <div className="onb-code-head">
        <span className="onb-code-label mono">{block.label}</span>
        <CopyButton
          value={block.code}
          label={block.copyLabel}
          onCopy={block.countsAsSnippetViewed ? onSnippetViewed : undefined}
        />
      </div>
      <pre className="onb-code-body">{block.code}</pre>
    </div>
  );
}

function KeysStep({
  createdKey,
  onBack,
  onChanged,
  onContinue,
  onKeyCreated,
  onUseMetadata,
  path,
  provider,
  status,
}: {
  createdKey: ApiKeyCreated | null;
  onBack: (() => void) | null;
  onChanged: () => void;
  onContinue: () => void;
  onKeyCreated: (key: ApiKeyCreated) => void;
  onUseMetadata: () => void;
  path: IntegrationPath;
  provider: ProviderId;
  status: OnboardingStatus;
}) {
  const providerConnection = status.provider_connections.find((c) => c.provider === provider);
  const providerConnected = providerConnection?.status === "connected";
  const keysReady = status.has_api_key && (!path.requiresProviderConnection || providerConnected);

  return (
    <>
      <VarstenKeyPanel createdKey={createdKey} onChanged={onChanged} onKeyCreated={onKeyCreated} status={status} />
      {path.requiresProviderConnection ? (
        <ProviderKeyPanel
          connection={providerConnection}
          isSdk={path.method === "sdk"}
          onChanged={onChanged}
          onUseMetadata={onUseMetadata}
          provider={provider}
        />
      ) : null}
      <StepFooter
        onBack={onBack}
        primary={{ label: "Continue", onClick: onContinue, disabled: !keysReady }}
        secondary={
          path.requiresProviderConnection ? (
            <button className="onb-linkbtn" onClick={onUseMetadata}>
              No provider key? Switch to metadata only
            </button>
          ) : undefined
        }
      />
    </>
  );
}

function VarstenKeyPanel({
  createdKey,
  onChanged,
  onKeyCreated,
  status,
}: {
  createdKey: ApiKeyCreated | null;
  onChanged: () => void;
  onKeyCreated: (key: ApiKeyCreated) => void;
  status: OnboardingStatus;
}) {
  const { activeProjectId, getToken } = useSession();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async () => {
    if (!activeProjectId) return;
    setBusy(true);
    setErr(null);
    try {
      onKeyCreated(await api.createApiKey(await getToken(), activeProjectId, "default"));
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="onb-panel">
      <div className="onb-panel-head">
        <div className="onb-panel-title">Varsten API key</div>
        {status.has_api_key ? <span className="onb-status pos"><span className="onb-dot-sq" />Created</span> : null}
      </div>
      {createdKey ? (
        <>
          <div className="onb-note pos">Copy this now — it is shown once and never again.</div>
          <div className="onb-code">
            <div className="onb-code-head">
              <span className="onb-code-label mono">VARSTEN_API_KEY</span>
              <CopyButton value={createdKey.plaintext_key} label="Copy key" />
            </div>
            <pre className="onb-code-body">{createdKey.plaintext_key}</pre>
          </div>
        </>
      ) : status.has_api_key ? (
        <div className="onb-note">
          A key already exists for this project. Continue with it, or{" "}
          <button className="onb-linkbtn" disabled={busy} onClick={() => void create()}>
            {busy ? "creating…" : "create another"}
          </button>{" "}
          — the old key keeps working.
        </div>
      ) : (
        <>
          <div className="onb-note">
            Identifies this project&apos;s traffic to Varsten. It starts with <span className="mono">vk_</span> and is
            shown once at creation.
          </div>
          <div className="onb-panel-actions">
            <button className="btn primary" disabled={busy || !activeProjectId} onClick={() => void create()}>
              {busy ? "Creating…" : "Create API key"}
            </button>
          </div>
        </>
      )}
      {err ? <div className="onb-note neg">{err}</div> : null}
    </section>
  );
}

function ProviderKeyPanel({
  connection,
  isSdk,
  onChanged,
  onUseMetadata,
  provider,
}: {
  connection: ProviderConnectionStatus | undefined;
  isSdk: boolean;
  onChanged: () => void;
  onUseMetadata: () => void;
  provider: ProviderId;
}) {
  const connected = connection?.status === "connected";
  const providerKey = useProviderKeyConnect({ onChanged, provider });

  return (
    <section className="onb-panel onb-provider">
      <div className="onb-panel-head">
        <div className="onb-panel-title">{PROVIDER_LABELS[provider]} key</div>
        <ProviderConnectedStatus connected={connected} connection={connection} />
      </div>
      <ProviderKeySetup connected={connected} isSdk={isSdk} provider={provider} providerKey={providerKey} />
      <ProviderKeyStatus
        connection={connection}
        connected={connected}
        manualSetup={providerKey.manualSetup}
        onUseMetadata={onUseMetadata}
        provider={provider}
        providerError={providerKey.err}
      />
    </section>
  );
}

type ProviderKeyConnectState = ReturnType<typeof useProviderKeyConnect>;

function ProviderKeySetup({
  connected,
  isSdk,
  provider,
  providerKey,
}: {
  connected: boolean;
  isSdk: boolean;
  provider: ProviderId;
  providerKey: ProviderKeyConnectState;
}) {
  if (connected) return null;
  return (
    <>
      <ProviderKeyNotice isSdk={isSdk} provider={provider} />
      <ProviderKeyForm
        busy={providerKey.busy}
        onConnect={providerKey.connect}
        onValueChange={providerKey.setValue}
        provider={provider}
        value={providerKey.value}
      />
    </>
  );
}

function ProviderKeyStatus({
  connected,
  connection,
  manualSetup,
  onUseMetadata,
  provider,
  providerError,
}: {
  connected: boolean;
  connection: ProviderConnectionStatus | undefined;
  manualSetup: boolean;
  onUseMetadata: () => void;
  provider: ProviderId;
  providerError: string | null;
}) {
  const error = providerError ?? (connected ? undefined : connection?.last_error);
  return (
    <>
      {error ? <div className="onb-note neg">{error}</div> : null}
      {manualSetup ? <ManualProviderSetupNote onUseMetadata={onUseMetadata} provider={provider} /> : null}
    </>
  );
}

function useProviderKeyConnect({ onChanged, provider }: { onChanged: () => void; provider: ProviderId }) {
  const { activeProjectId, getToken } = useSession();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [manualSetup, setManualSetup] = useState(false);

  const connect = async () => {
    const apiKey = value.trim();
    if (!activeProjectId || !apiKey) return;
    setBusy(true);
    setErr(null);
    setManualSetup(false);
    try {
      await api.connectProjectProvider(await getToken(), activeProjectId, provider, apiKey);
      setValue("");
      onChanged();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (e instanceof ApiError && (e.status === 409 || e.code === "provider_key_storage_unavailable")) {
        setManualSetup(true);
      } else {
        setErr(message);
      }
    } finally {
      setBusy(false);
    }
  };

  return { busy, connect, err, manualSetup, setValue, value };
}

function ProviderConnectedStatus({
  connected,
  connection,
}: {
  connected: boolean;
  connection: ProviderConnectionStatus | undefined;
}) {
  if (!connected) return null;
  return (
    <span className="onb-status pos">
      <span className="onb-dot-sq" />
      Connected{connection?.last_verified_at ? ` · ${new Date(connection.last_verified_at).toLocaleString()}` : ""}
    </span>
  );
}

function ProviderKeyNotice({ isSdk, provider }: { isSdk: boolean; provider: ProviderId }) {
  return (
    <div className="onb-note">
      <strong>Encrypted at rest, used only to reach {PROVIDER_LABELS[provider]}, never shown again</strong> or
      written to our logs. Only token counts and scores leave your account — never prompt or completion text.
      {isSdk ? (
        <>
          {" "}Your app keeps its own copy of this key, used only if Varsten is ever unreachable, so an outage falls
          straight back to your provider.
        </>
      ) : null}
    </div>
  );
}

function ProviderKeyForm({
  busy,
  onConnect,
  onValueChange,
  provider,
  value,
}: {
  busy: boolean;
  onConnect: () => Promise<void>;
  onValueChange: (value: string) => void;
  provider: ProviderId;
  value: string;
}) {
  return (
    <div className="onb-panel-actions row">
      <input
        className="input"
        type="password"
        placeholder={PROVIDER_KEY_PLACEHOLDERS[provider]}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && void onConnect()}
        style={{ flex: 1 }}
      />
      <button className="btn primary" disabled={busy || !value.trim()} onClick={() => void onConnect()}>
        {busy ? "Connecting…" : "Connect"}
      </button>
    </div>
  );
}

function ManualProviderSetupNote({ onUseMetadata, provider }: { onUseMetadata: () => void; provider: ProviderId }) {
  return (
    <div className="onb-note warn">
      This environment cannot store {PROVIDER_LABELS[provider]} keys from the dashboard yet — a Varsten operator
      needs to finish vault setup, and your traffic is not affected. Don&apos;t want to wait?{" "}
      <button className="onb-linkbtn" onClick={onUseMetadata}>Switch to metadata only</button> (no provider key), or{" "}
      <a className="onb-inline-link" href={SETUP_CALL_HREF}>book a setup call</a>.
    </div>
  );
}

// --- step 3: install & verify ------------------------------------------------------

function fmtUsd(v?: string | null): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `$${n.toFixed(6)}` : "—";
}

// The ledger's pricing_status is an internal enum; never show it raw to a user.
function pricingStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case null:
    case undefined:
    case "":
      return "pricing pending";
    case "priced":
      return "priced from our catalog";
    case "model_not_in_catalog":
      return "model not in our price catalog yet";
    case "missing_token_counts":
      return "missing token counts";
    case "missing_reported_cost":
      return "no reported cost to fall back on";
    case "suspected_model_alias":
      return "possible model alias";
    default:
      return status.replace(/_/g, " ");
  }
}

function providerLabel(provider: ProviderId | string | null | undefined): string {
  return PROVIDER_LABELS[(provider ?? "openai") as ProviderId] ?? String(provider);
}

function methodLabel(method: string | null | undefined): string {
  switch (method) {
    case "sdk":
      return "Production SDK";
    case "base_url":
      return "base URL";
    case "metadata":
      return "metadata ingestion";
    default:
      return "no matching traffic";
  }
}

function expectedSignal(path: IntegrationPath, provider: ProviderId): string {
  if (path.method === "metadata") return "a usage record posted to the metadata ingest endpoint";
  if (path.method === "sdk") return `${providerLabel(provider)} traffic carrying the Varsten SDK marker`;
  return `${providerLabel(provider)} traffic through the Varsten base URL without an SDK marker`;
}

type IntegrationProviderSignal = OnboardingIntegration["providers"][number];
type HealthContext = {
  match: IntegrationProviderSignal | undefined;
  path: IntegrationPath;
  provider: ProviderId;
  seenMethod: IntegrationProviderSignal | undefined;
};
type HealthRule = {
  matches: (context: HealthContext) => boolean;
  render: (context: HealthContext) => ReactNode;
};

const integrationHealthRules: HealthRule[] = [
  {
    matches: ({ match, path }) => path.method === "sdk" && match?.method === "sdk",
    render: ({ match }) => (
      <div className="onb-status pos block">
        <span className="onb-dot-sq" />
        Fail-open SDK detected{match?.sdk_client ? ` (${match.sdk_client})` : ""}. You are production-safe.
      </div>
    ),
  },
  {
    matches: ({ match, path }) => path.method === "base_url" && match?.method === "base_url",
    render: ({ provider }) => (
      <div className="onb-status pos block">
        <span className="onb-dot-sq" />
        Base-URL traffic detected for {providerLabel(provider)}. This evaluation path is live.
      </div>
    ),
  },
  {
    matches: ({ match, path }) => path.method === "sdk" && match?.method === "base_url",
    render: ({ provider }) => (
      <div className="onb-note warn" style={{ marginTop: 10 }}>
        We detected {providerLabel(provider)} base-URL traffic, but you chose the Production SDK.
        Install the SDK wrapper so Varsten can verify fail-open behavior before setup is complete.
      </div>
    ),
  },
  {
    matches: ({ path, seenMethod }) => path.method === "metadata" && seenMethod?.method === "metadata",
    render: () => (
      <div className="onb-status pos block">
        <span className="onb-dot-sq" />
        Metadata ingestion is live. Nothing is inline and no content left your boundary.
      </div>
    ),
  },
];

function IntegrationHealth({
  integration,
  path,
  provider,
}: {
  integration: OnboardingIntegration;
  path: IntegrationPath;
  provider: ProviderId;
}) {
  const match = integration.providers.find((p) => p.provider === provider);
  const seenMethod = integration.providers.find((p) => p.method !== "none");
  const context = { match, path, provider, seenMethod };
  const rule = integrationHealthRules.find((candidate) => candidate.matches(context));

  return rule ? rule.render(context) : null;
}

function VerifyStep({
  completionError,
  createdKey,
  language,
  onBack,
  onFinish,
  onLeave,
  onSnippetViewed,
  path,
  provider,
  status,
}: {
  completionError: string | null;
  createdKey: ApiKeyCreated | null;
  language: LanguageId;
  onBack: (() => void) | null;
  onFinish: () => void;
  onLeave: () => void;
  onSnippetViewed: () => void | Promise<void>;
  path: IntegrationPath;
  provider: ProviderId;
  status: OnboardingStatus;
}) {
  const fr = status.first_request;
  const recipe = useMemo(
    () => buildRecipe({ path: path.id, provider, language, varstenKey: createdKey?.plaintext_key ?? null }),
    [path.id, provider, language, createdKey],
  );

  return (
    <>
      <PathInstallNote path={path} />
      <RecipeBlocks
        hasApiKey={status.has_api_key}
        hasFreshKey={Boolean(createdKey)}
        onSnippetViewed={onSnippetViewed}
        recipe={recipe}
      />

      <div className="onb-verify">
        <VerificationResult fr={fr} path={path} provider={provider} status={status} />
      </div>

      {completionError ? <div className="onb-note neg">{completionError}</div> : null}
      <StepFooter
        onBack={onBack}
        primary={{
          label: status.can_complete ? "Finish setup" : "Waiting for verification",
          onClick: onFinish,
          disabled: !status.can_complete,
        }}
        secondary={
          <button className="onb-linkbtn" onClick={onLeave}>
            Leave setup without finishing
          </button>
        }
      />
    </>
  );
}

function PathInstallNote({ path }: { path: IntegrationPath }) {
  const notes: Record<IntegrationPathId, ReactNode> = {
    base_url: (
      <div className="onb-note warn">
        Fastest way to see traffic. <strong>Evaluation only</strong> — base-URL mode keeps Varsten in your request
        path with no way around it, so it is not fail-open. Move to the SDK before this route is production-critical.
      </div>
    ),
    sdk: (
      <div className="onb-note">
        The SDK routes healthy traffic through Varsten and falls back straight to your provider if Varsten is ever
        unreachable — an outage costs you savings for a few minutes, never your uptime.
      </div>
    ),
    metadata: (
      <div className="onb-note">
        The safest start: nothing sits in your request path and no content leaves your boundary. After each LLM
        call, POST token counts and labels.
      </div>
    ),
  };
  return notes[path.id];
}

function RecipeBlocks({
  hasApiKey,
  hasFreshKey,
  onSnippetViewed,
  recipe,
}: {
  hasApiKey: boolean;
  hasFreshKey: boolean;
  onSnippetViewed: () => void | Promise<void>;
  recipe: ReturnType<typeof buildRecipe>;
}) {
  return (
    <div className="onb-recipe">
      {recipe.map((block) => (
        <CodeBlock key={block.id} block={block} onSnippetViewed={onSnippetViewed} />
      ))}
      {!hasFreshKey && hasApiKey ? (
        <div className="onb-note subtle">
          <span className="mono">VARSTEN_API_KEY</span> is the <span className="mono">vk_</span> key created in the
          Keys step — it was shown once at creation.
        </div>
      ) : null}
    </div>
  );
}

function VerificationResult({
  fr,
  path,
  provider,
  status,
}: {
  fr: OnboardingStatus["first_request"];
  path: IntegrationPath;
  provider: ProviderId;
  status: OnboardingStatus;
}) {
  if (!status.can_complete) {
    return (
      <>
        <WaitingForFirstRequest path={path} provider={provider} status={status} />
        {fr.seen ? <FirstRequestDetails fr={fr} integration={status.integration} path={path} provider={provider} /> : null}
      </>
    );
  }

  return (
    <>
      <VerifiedStatus source={fr.source} />
      <FirstRequestDetails fr={fr} integration={status.integration} path={path} provider={provider} />
      <NextSteps path={path} />
    </>
  );
}

function VerifiedStatus({ source }: { source: OnboardingStatus["first_request"]["source"] }) {
  return (
    <div className="onb-status pos block strong">
      <span className="onb-dot-sq" />
      {source === "ingest"
        ? "Verified live: first usage record received. Varsten is measuring your AI traffic."
        : "Verified live: first request received through the selected integration."}
    </div>
  );
}

function NextSteps({ path }: { path: IntegrationPath }) {
  return (
    <div className="onb-next">
      <div className="onb-field-label mono">NEXT</div>
      {path.method === "sdk" ? (
        <>
          <div className="onb-note">
            <strong>Prove fail-open before you roll out.</strong> Point the SDK at a dead port in a non-production
            shell. The request should still complete through your provider and your{" "}
            <span className="mono">onFallback</span> handler should fire.
          </div>
          <CodeBlock block={{ id: "self-test", label: "TERMINAL", code: SDK_FAILOPEN_TEST, copyLabel: "Copy self-test" }} />
        </>
      ) : null}
      {path.method === "base_url" ? (
        <div className="onb-note">
          <strong>Before production:</strong> move this route to the fail-open Production SDK — same key, same
          provider connection, no re-onboarding. Until then, keep this path on evaluation traffic.
        </div>
      ) : null}
      {path.method === "metadata" ? (
        <div className="onb-note">
          <strong>Sharpen attribution:</strong> add <span className="mono">feature</span>,{" "}
          <span className="mono">workflow</span>, and <span className="mono">task_type</span> to each record to break
          spend down by workload. Inline optimization needs an SDK or gateway path later.
        </div>
      ) : null}
      <div className="onb-note">
        As traffic builds, your <strong>Dashboard</strong> fills in live spend and the cuts worth real money, and{" "}
        <strong>Savings</strong> starts a verified savings number you can take to finance.
      </div>
    </div>
  );
}

function FirstRequestDetails({
  fr,
  integration,
  path,
  provider,
}: {
  fr: OnboardingStatus["first_request"];
  integration: OnboardingIntegration;
  path: IntegrationPath;
  provider: ProviderId;
}) {
  return (
    <>
      <table className="tbl" style={{ marginTop: 12 }}>
        <tbody>
          <tr><td className="muted">Provider</td><td>{fr.provider}</td></tr>
          <tr><td className="muted">Model</td><td>{fr.model}</td></tr>
          <tr><td className="muted">Measured cost</td><td>{fmtUsd(fr.cost_usd)} <span className="muted">({pricingStatusLabel(fr.pricing_status)})</span></td></tr>
          <tr><td className="muted">Tokens</td><td>{fr.input_tokens} in / {fr.output_tokens} out</td></tr>
          <tr><td className="muted">Latency</td><td>{fr.latency_ms ?? "—"} ms</td></tr>
          <tr><td className="muted">Environment</td><td>{fr.environment ?? "—"}</td></tr>
          <tr><td className="muted">Request id</td><td>{fr.request_id ?? "—"}</td></tr>
          <tr><td className="muted">Task / workflow</td><td>{fr.task_type ?? fr.workflow ?? fr.feature ?? "—"}</td></tr>
        </tbody>
      </table>
      <div className={`pill ${fr.metadata_quality.level === "great" ? "green" : "neutral"}`} style={{ marginTop: 12 }}>
        {fr.metadata_quality.message}
      </div>
      <IntegrationHealth integration={integration} path={path} provider={provider} />
    </>
  );
}

function WaitingForFirstRequest({
  path,
  provider,
  status,
}: {
  path: IntegrationPath;
  provider: ProviderId;
  status: OnboardingStatus;
}) {
  // Surface a helpful nudge if the first request is slow to arrive, so the funnel
  // never spins forever with no guidance.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setSlow(true), 45000);
    return () => window.clearTimeout(id);
  }, []);
  return (
    <div className="onb-waiting">
      <div className="onb-note" style={{ fontWeight: 600, color: "var(--text)", marginTop: 0 }}>
        Run or deploy this change. Finish unlocks when Varsten verifies {expectedSignal(path, provider)}.
      </div>
      <div className="onb-waiting-row" style={{ marginTop: 8 }}>
        <div className="spinner" />
        <span>
          {status.verified_method
            ? `Detected ${methodLabel(status.verified_method)} traffic, but not the selected ${methodLabel(path.method)} setup yet.`
            : path.method === "metadata"
              ? "Listening for your first usage record — this page updates the instant it lands."
              : "Listening for your first request — this page updates the instant it lands."}
        </span>
      </div>
      {status.missing_steps.length ? (
        <ul style={{ margin: "10px 0 0", paddingLeft: 18 }}>
          {status.missing_steps.map((step) => (
            <li className="es" key={step.key} style={{ listStyle: "disc" }}>{step.label}</li>
          ))}
        </ul>
      ) : null}
      {slow ? (
        <div className="onb-note" style={{ marginTop: 10 }}>
          Nothing yet? That&apos;s fine — traffic can take a while to reach a new integration. If you expected
          it sooner, check that you are using your <span className="mono">vk_</span> Varsten key
          {path.method === "metadata" ? (
            <> and POSTing to <span className="mono">{PROXY_BASE}/usage-events</span>.</>
          ) : (
            <>, the base URL matches the snippet above, and the request used a connected provider (for example{" "}
              <span className="mono">{EXAMPLE_MODELS[provider]}</span>).</>
          )}
        </div>
      ) : null}
    </div>
  );
}
