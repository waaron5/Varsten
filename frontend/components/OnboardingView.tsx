"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import { useSession } from "@/components/session";
import { ApiError, api } from "@/lib/api";
import { currentOnboardingIntent } from "@/lib/onboardingIntent";
import {
  BASE_URL_PROVIDER_SNIPPETS,
  BASE_URL_SNIPPET,
  DOCS_HREF,
  INTEGRATION_PATHS,
  METADATA_SNIPPET,
  PROXY_BASE,
  SDK_FAILOPEN_TEST,
  SDK_INSTALL,
  SDK_SNIPPET,
  integrationPath,
  type IntegrationPath,
  type IntegrationPathId,
} from "@/lib/integrationSnippets";
import type { ApiKeyCreated, OnboardingIntegration, OnboardingStatus } from "@/lib/types";

const SETUP_CALL_HREF = "mailto:mail@varsten.ai?subject=Varsten%20setup%20call";
type ProviderId = "openai" | "anthropic" | "gemini";
type ProviderDefinition = (typeof PROVIDERS)[number];
type ProviderConnectionStatus = OnboardingStatus["provider_connections"][number];

const PROVIDERS: {
  id: ProviderId;
  name: string;
  description: string;
  placeholder: string;
  endpoint: string;
}[] = [
  {
    id: "openai",
    name: "OpenAI",
    description: "OpenAI-compatible chat completions and tool calls.",
    placeholder: "sk-...",
    endpoint: `${PROXY_BASE}/chat/completions`,
  },
  {
    id: "anthropic",
    name: "Anthropic",
    description: "Native Messages, count_tokens, streaming, and batches.",
    placeholder: "sk-ant-...",
    endpoint: `${PROXY_BASE}/messages`,
  },
  {
    id: "gemini",
    name: "Gemini",
    description: "Gemini native v1beta and OpenAI-compatible chat routes.",
    placeholder: "AIza...",
    endpoint: `${PROXY_BASE}/v1beta/models/{model}:generateContent`,
  },
];

const CODE_STYLE: React.CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: 12,
  fontFamily: "var(--font-geist-mono, monospace)",
  fontSize: 12,
  lineHeight: 1.5,
  overflowX: "auto",
  whiteSpace: "pre",
  margin: "10px 0 0",
};

// Step icons (single-path, stroked — matches the app's Icon convention).
const STEP_ICONS: Record<StepKey, string> = {
  path: "M6 3v12 M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 6a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 6a9 9 0 0 1-9 9",
  "api-key": "M8 15a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M11 11h9 M17 11v3 M20 11v2",
  provider: "M12 8V3 M8 8V4 M16 8V4 M7 8h10v3a5 5 0 0 1-10 0V8z M12 16v5",
  connect: "M3 12h4l2 6 4-14 2 8h6",
};
const CHECK_ICON = "M20 6L9 17l-5-5";

function OnbIcon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function pathStorageKey(projectId: string): string {
  return `varsten:onboarding-path:${projectId}`;
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

  const firstSeen = data?.first_request.seen ?? false;

  // Poll for the first request only while we are still waiting for one. Stops as
  // soon as it arrives, and caps total polling so a tab left open overnight
  // waiting on a deploy does not hammer the API indefinitely.
  useEffect(() => {
    if (!data || firstSeen) return;
    const startedAt = Date.now();
    const maxDurationMs = 20 * 60 * 1000;
    const id = window.setInterval(() => {
      if (Date.now() - startedAt > maxDurationMs) {
        window.clearInterval(id);
        return;
      }
      void reload();
    }, 4000);
    return () => window.clearInterval(id);
  }, [data, firstSeen, reload]);

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
    try {
      await recordEvent("dashboard_entered");
      await api.completeOnboarding(await getToken(), activeProjectId ?? undefined);
    } catch {
      // Completion is best-effort; the dashboard still works if it fails.
    }
    router.push("/dashboard");
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

  return <OnboardingWizard status={data} onReload={() => void reload()} onFinish={() => void finish()} onSnippetViewed={() => void recordEvent("snippet_viewed")} />;
}

// --- wizard step model -------------------------------------------------------

type StepKey = "path" | "api-key" | "provider" | "connect";

interface StepMeta {
  key: StepKey;
  label: string; // short label under the stepper node
  done: boolean;
}

function hasProgress(status: OnboardingStatus): boolean {
  return status.has_api_key || status.has_provider_connection || status.first_request.seen;
}

// A step counts as "done" only once the user has genuinely finished it. The path
// step has a sensible default, so it's done only after the user has moved past it
// (pastPath) — never green on first paint.
function buildSteps(status: OnboardingStatus, path: IntegrationPath, pastPath: boolean): StepMeta[] {
  const steps: StepMeta[] = [
    { key: "path", label: "Connect", done: pastPath },
    { key: "api-key", label: "API key", done: status.has_api_key },
  ];
  if (path.requiresProviderConnection) {
    steps.push({ key: "provider", label: "Provider", done: status.has_provider_connection });
  }
  steps.push({ key: "connect", label: "Verify", done: status.first_request.seen });
  return steps;
}

function stepHead(key: StepKey, status: OnboardingStatus, path: IntegrationPath): { title: string; sub: string } {
  switch (key) {
    case "path":
      return {
        title: "How do you want to connect?",
        sub: status.observe_only
          ? "Varsten measures your AI spend and surfaces where it can be cut. First, choose how your traffic reaches us — nothing changes in production until you turn on optimization."
          : "Varsten cuts your AI spend and proves it. First, choose how your traffic reaches us — you can move up the ladder later without re-integrating.",
      };
    case "api-key":
      return {
        title: "Create your Varsten key",
        sub: "Use this key in place of your provider key when you call Varsten.",
      };
    case "provider":
      return {
        title: "Connect your provider",
        sub: "Varsten uses your provider key to forward and optimize your calls on your behalf.",
      };
    case "connect":
      return path.method === "metadata"
        ? { title: "Send a usage record", sub: "Last step. Drop the snippet into your app — Varsten starts measuring the moment your first record arrives." }
        : { title: "Send your first request", sub: "Last step. Drop the snippet into your app — Varsten starts measuring the moment your first request flows." };
  }
}

// --- top progress stepper ----------------------------------------------------

// Completion is positional: a node only turns green + checked once the user has
// advanced past it. The active step is highlighted but never shown as complete,
// and upcoming steps stay neutral even if their backing status happens to be set.
function WizardStepper({ steps, activeIndex }: { steps: StepMeta[]; activeIndex: number }) {
  return (
    <ol className="onb-stepper" aria-label="Setup progress">
      {steps.map((step, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        const status = done ? "completed" : active ? "current" : "upcoming";
        return (
          <li key={step.key} className="onb-stepper-seg" aria-current={active ? "step" : undefined}>
            {i > 0 ? <div className={`onb-line${i <= activeIndex ? " done" : ""}`} aria-hidden="true" /> : null}
            <div className={`onb-node${done ? " done" : ""}${active ? " active" : ""}`}>
              <div className="onb-dot" aria-hidden="true">
                <OnbIcon path={done ? CHECK_ICON : STEP_ICONS[step.key]} />
              </div>
              <div className="onb-node-label">
                {step.label}
                <span className="onb-sr-only"> — {status}</span>
              </div>
            </div>
          </li>
        );
      })}
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
  secondary?: React.ReactNode;
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

function OnboardingWizard({
  status,
  onReload,
  onFinish,
  onSnippetViewed,
}: {
  status: OnboardingStatus;
  onReload: () => void;
  onFinish: () => void;
  onSnippetViewed: () => void;
}) {
  const [pathId, setPathId] = useState<IntegrationPathId>(() => {
    if (typeof window !== "undefined") {
      const saved = window.localStorage.getItem(pathStorageKey(status.project_id));
      if (saved && INTEGRATION_PATHS.some((p) => p.id === saved)) return saved as IntegrationPathId;
    }
    return defaultPathForIntent();
  });
  const path = integrationPath(pathId);

  // The path step defaults sensibly but is only "done" once the user has moved
  // past it. A returning user who has already generated a key / connected a
  // provider / sent traffic is clearly past it, so seed from real progress.
  const [pastPath, setPastPath] = useState(() => hasProgress(status));
  const steps = useMemo(() => buildSteps(status, path, pastPath), [status, path, pastPath]);

  // manualKey is the user's explicit position in the wizard (set by Back /
  // Continue). Whenever it no longer names a step in the current list — e.g. a
  // path switch hid the provider step — this falls through to the first
  // incomplete step, computed at render time rather than corrected in an effect.
  const [manualKey, setManualKey] = useState<StepKey | null>(null);
  const openKey = useMemo<StepKey>(() => {
    if (manualKey && steps.some((s) => s.key === manualKey)) return manualKey;
    const firstIncomplete = steps.find((s) => !s.done);
    return firstIncomplete?.key ?? steps[steps.length - 1].key;
  }, [manualKey, steps]);

  const currentIndex = steps.findIndex((s) => s.key === openKey);
  const goNext = useCallback(() => {
    setManualKey(steps[Math.min(currentIndex + 1, steps.length - 1)].key);
  }, [steps, currentIndex]);
  const goBack = currentIndex > 0 ? () => setManualKey(steps[currentIndex - 1].key) : null;

  const selectPath = useCallback(
    (id: IntegrationPathId) => {
      setPathId(id);
      try {
        window.localStorage.setItem(pathStorageKey(status.project_id), id);
      } catch {
        // Non-fatal; the choice still applies for this session.
      }
    },
    [status.project_id],
  );

  const head = stepHead(openKey, status, path);

  return (
    <div className="view">
      <div className="onb">
        <WizardStepper steps={steps} activeIndex={currentIndex} />

        <div className="onb-head">
          <h2 className="onb-title">{head.title}</h2>
          <p className="onb-sub">{head.sub}</p>
        </div>

        <div className="onb-body">
          {openKey === "path" && (
            <PathStep active={pathId} onSelect={selectPath} onContinue={() => { setPastPath(true); goNext(); }} />
          )}
          {openKey === "api-key" && (
            <ApiKeyStep status={status} onBack={goBack} onComplete={goNext} />
          )}
          {openKey === "provider" && (
            <ProviderStep
              status={status}
              isSdk={path.method === "sdk"}
              onBack={goBack}
              onChanged={onReload}
              onConnected={goNext}
              onUseMetadata={() => selectPath("metadata")}
            />
          )}
          {openKey === "connect" && (
            <ConnectAndVerifyStep status={status} path={path} onBack={goBack} onSnippetViewed={onSnippetViewed} onFinish={onFinish} />
          )}
        </div>

        <div className="onb-help">
          <a href={DOCS_HREF} target="_blank" rel="noreferrer">View docs</a>
          <a href={SETUP_CALL_HREF}>Book a setup call</a>
        </div>
      </div>
    </div>
  );
}

function Tag({ label, tone }: { label: string; tone: "pos" | "neg" | "neutral" }) {
  return <span className={`onb-tag${tone === "pos" ? " pos" : tone === "neg" ? " neg" : ""}`}>{label}</span>;
}

const PATH_ICONS: Record<IntegrationPathId, string> = {
  sdk: "M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6l7-3z M9 12l2 2 4-4",
  base_url: "M13 2L4 14h6l-1 8 9-12h-6l1-8z",
  metadata: "M7 3h8l4 4v14H7z M15 3v5h5 M10 13h6 M10 17h4",
};

function PathStep({
  active,
  onSelect,
  onContinue,
}: {
  active: IntegrationPathId;
  onSelect: (id: IntegrationPathId) => void;
  onContinue: () => void;
}) {
  return (
    <>
      <div className="onb-options">
        {INTEGRATION_PATHS.map((p) => (
          <PathOption key={p.id} path={p} active={p.id === active} onSelect={() => onSelect(p.id)} />
        ))}
      </div>
      <StepFooter onBack={null} primary={{ label: "Continue", onClick: onContinue }} />
    </>
  );
}

function PathOption({ path, active, onSelect }: { path: IntegrationPath; active: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className={`onb-option${active ? " active" : ""}`} aria-pressed={active}>
      <span className="onb-option-icon"><OnbIcon path={PATH_ICONS[path.id]} /></span>
      <span className="onb-option-main">
        <span className="onb-option-name">
          {path.name}
          <span className="onb-option-bestfor">Best for {path.bestFor.toLowerCase()}</span>
          {path.recommended ? <span className="pill green">Recommended</span> : null}
        </span>
        <span className="onb-option-tagline">{path.tagline}</span>
        <span className="onb-tags">
          <Tag
            label={path.failOpen === "yes" ? "Fail-open" : path.failOpen === "no" ? "Not fail-open" : "Nothing inline"}
            tone={path.failOpen === "no" ? "neg" : "pos"}
          />
          <Tag label={path.seesContent ? "Sees content" : "Metadata only"} tone={path.seesContent ? "neutral" : "pos"} />
          <Tag label={path.needsProviderKey ? "Provider key" : "No provider key"} tone="neutral" />
          <Tag label={path.unlocksOptimize ? "Can optimize" : "Measure only"} tone="neutral" />
        </span>
      </span>
      <span className="onb-radio" aria-hidden="true" />
    </button>
  );
}

function CopyButton({ value, label = "Copy", onCopy }: { value: string; label?: string; onCopy?: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="btn"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable; the value is selectable in the block */
        }
        onCopy?.();
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

function ApiKeyStep({ status, onBack, onComplete }: { status: OnboardingStatus; onBack: (() => void) | null; onComplete: () => void }) {
  const { activeProjectId, getToken } = useSession();
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async () => {
    if (!activeProjectId) return;
    setBusy(true);
    setErr(null);
    try {
      setCreated(await api.createApiKey(await getToken(), activeProjectId, "default"));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // A freshly created key's plaintext is shown exactly once. Never auto-advance
  // out of this state — the user must explicitly continue after copying it.
  if (created) {
    return (
      <>
        <div className="onb-note pos">Copy this now — you won&apos;t be able to see it again.</div>
        <pre style={CODE_STYLE}>{created.plaintext_key}</pre>
        <div style={{ marginTop: 10 }}><CopyButton value={created.plaintext_key} label="Copy key" /></div>
        {err ? <div className="onb-note neg">{err}</div> : null}
        <StepFooter onBack={onBack} primary={{ label: "Continue", onClick: onComplete }} />
      </>
    );
  }

  if (status.has_api_key) {
    return (
      <>
        <div className="onb-note">
          A key already exists for this project. Continue with it, or create another only if you need to — the old key keeps working.
        </div>
        {err ? <div className="onb-note neg">{err}</div> : null}
        <StepFooter
          onBack={onBack}
          primary={{ label: "Continue", onClick: onComplete }}
          secondary={
            <button className="onb-linkbtn" disabled={busy} onClick={() => void create()}>
              {busy ? "Creating…" : "Create another key"}
            </button>
          }
        />
      </>
    );
  }

  return (
    <>
      <div className="onb-note">
        Generate a Varsten key for this project. It is shown once, so keep it somewhere safe.
      </div>
      {err ? <div className="onb-note neg">{err}</div> : null}
      <StepFooter
        onBack={onBack}
        primary={{ label: busy ? "Creating…" : "Create API key", onClick: () => void create(), disabled: busy || !activeProjectId }}
      />
    </>
  );
}

function ProviderStep({
  status,
  isSdk,
  onBack,
  onChanged,
  onConnected,
  onUseMetadata,
}: {
  status: OnboardingStatus;
  isSdk: boolean;
  onBack: (() => void) | null;
  onChanged: () => void;
  onConnected: () => void;
  onUseMetadata: () => void;
}) {
  const { activeProjectId, getToken } = useSession();
  const [keys, setKeys] = useState<Record<ProviderId, string>>({ openai: "", anthropic: "", gemini: "" });
  const [busy, setBusy] = useState<ProviderId | null>(null);
  const [errors, setErrors] = useState<Partial<Record<ProviderId, string>>>({});
  const [manualSetup, setManualSetup] = useState<{ provider: string; message: string } | null>(null);
  const connectionByProvider = new Map(status.provider_connections.map((c) => [c.provider, c]));

  const connect = async (provider: ProviderId) => {
    const apiKey = keys[provider].trim();
    if (!activeProjectId || !apiKey) return;
    setBusy(provider);
    setErrors((current) => ({ ...current, [provider]: undefined }));
    try {
      await api.connectProjectProvider(await getToken(), activeProjectId, provider, apiKey);
      setKeys((current) => ({ ...current, [provider]: "" }));
      onChanged();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (e instanceof ApiError && (e.status === 409 || e.code === "provider_key_storage_unavailable")) {
        setManualSetup({ provider, message });
      } else {
        setErrors((current) => ({ ...current, [provider]: message }));
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="onb-keynote">
        <OnbIcon path="M5 11h14v10H5z M8 11V7a4 4 0 0 1 8 0v4" />
        <div className="onb-keynote-text">
          <strong>Encrypted at rest, used only to reach the provider, never shown again</strong> or written to
          our logs. Only token counts and scores leave your account — never prompt or completion text.
          {isSdk ? (
            <> On the SDK path your app also keeps its own copy of this key, used only if Varsten is ever
              unreachable, so an outage falls straight back to your provider.</>
          ) : null}
        </div>
      </div>
      <div className="onb-provider-list">
        {PROVIDERS.map((provider) => {
          const connection = connectionByProvider.get(provider.id);
          return (
            <ProviderConnectionCard
              busy={busy}
              connection={connection}
              error={errors[provider.id] ?? connection?.last_error ?? undefined}
              key={provider.id}
              onConnect={connect}
              onKeyChange={(value) => setKeys((current) => ({ ...current, [provider.id]: value }))}
              provider={provider}
              value={keys[provider.id]}
            />
          );
        })}
      </div>

      <StepFooter
        onBack={onBack}
        primary={{ label: "Continue", onClick: onConnected, disabled: !status.has_provider_connection }}
        secondary={
          <button className="onb-linkbtn" onClick={onUseMetadata}>
            No provider key? Switch to metadata only
          </button>
        }
      />

      {manualSetup && (
        <div className="modal-backdrop" role="presentation" onClick={() => setManualSetup(null)}>
          <div className="modal-card" role="dialog" aria-modal="true" aria-label="Manual provider setup" onClick={(e) => e.stopPropagation()}>
            <div className="card-head">
              <h3>Manual setup required</h3>
              <button className="btn" onClick={() => setManualSetup(null)}>Close</button>
            </div>
            <div style={{ padding: "0 20px 18px" }}>
              <div className="onb-note">
                This environment cannot store {manualSetup.provider} keys from the dashboard yet. Your traffic is not affected; a Varsten operator needs to finish vault setup.
              </div>
              <div className="onb-note" style={{ color: "var(--text-2)" }}>{manualSetup.message}</div>
              <div className="onb-note">
                Don&apos;t want to wait? The <strong>Metadata only</strong> path needs no provider key — send usage records async and start seeing spend now.
              </div>
              <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 14 }}>
                <button className="btn primary" onClick={() => { setManualSetup(null); onUseMetadata(); }}>
                  Switch to metadata only
                </button>
                <a className="btn" href={SETUP_CALL_HREF}>Book setup call</a>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function providerConnectionLabel(connection: ProviderConnectionStatus | undefined): string {
  if (connection?.status === "connected") return "Connected";
  if (connection?.status === "manual_setup_required") return "Manual setup";
  return "Not connected";
}

function ProviderConnectionCard({
  busy,
  connection,
  error,
  onConnect,
  onKeyChange,
  provider,
  value,
}: {
  busy: ProviderId | null;
  connection: ProviderConnectionStatus | undefined;
  error?: string;
  onConnect: (provider: ProviderId) => Promise<void>;
  onKeyChange: (value: string) => void;
  provider: ProviderDefinition;
  value: string;
}) {
  const connected = connection?.status === "connected";
  return (
    <div className="onb-provider">
      <div className="onb-provider-head">
        <div className="onb-provider-name">{provider.name}</div>
        <span className={`pill ${connected ? "green" : "neutral"}`}>{providerConnectionLabel(connection)}</span>
      </div>
      <div className="onb-provider-desc">{provider.description}</div>
      {connected ? (
        <ConnectedProvider connection={connection} />
      ) : (
        <ProviderKeyForm busy={busy} onConnect={onConnect} onKeyChange={onKeyChange} provider={provider} value={value} />
      )}
      {error && !connected ? <div className="onb-note neg">{error}</div> : null}
    </div>
  );
}

function ConnectedProvider({ connection }: { connection: ProviderConnectionStatus | undefined }) {
  const verifiedAt = connection?.last_verified_at ? ` ${new Date(connection.last_verified_at).toLocaleString()}` : "";
  return <div className="onb-note pos">Verified{verifiedAt}.</div>;
}

function ProviderKeyForm({
  busy,
  onConnect,
  onKeyChange,
  provider,
  value,
}: {
  busy: ProviderId | null;
  onConnect: (provider: ProviderId) => Promise<void>;
  onKeyChange: (value: string) => void;
  provider: ProviderDefinition;
  value: string;
}) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
      <input
        className="input"
        type="password"
        placeholder={provider.placeholder}
        value={value}
        onChange={(e) => onKeyChange(e.target.value)}
        style={{ flex: 1 }}
      />
      <button
        className="btn primary"
        disabled={busy !== null || !value.trim()}
        onClick={() => void onConnect(provider.id)}
      >
        {busy === provider.id ? "Connecting…" : "Connect"}
      </button>
    </div>
  );
}

function IntegrationSnippet({ path, onSnippetViewed }: { path: IntegrationPath; onSnippetViewed: () => void }) {
  if (path.id === "sdk") {
    return (
      <>
        <div className="onb-note">
          The SDK routes healthy traffic through Varsten and falls back straight to your provider if
          Varsten is ever unreachable — an outage costs you savings for a few minutes, never your
          uptime. The provider key in your app is used only for that direct fallback; Varsten optimizes
          with the encrypted copy you connected.
        </div>
        <div className="onb-install">
          {SDK_INSTALL.map((s) => (
            <div key={s.label} className="onb-install-row">
              <span className="onb-install-label">{s.label}</span>
              <span className="mono">{s.value}</span>
            </div>
          ))}
        </div>
        <pre style={CODE_STYLE}>{SDK_SNIPPET}</pre>
        <div style={{ marginTop: 10 }}><CopyButton value={SDK_SNIPPET} label="Copy SDK snippet" onCopy={onSnippetViewed} /></div>
      </>
    );
  }

  if (path.id === "base_url") {
    return (
      <>
        <div className="onb-note warn">
          Fastest way to see traffic. <strong>Evaluation only</strong> — base-URL mode keeps Varsten
          in your request path with no way around it, so it is not fail-open. Move to the SDK before
          this route is production-critical.
        </div>
        <div className="onb-install">
          {BASE_URL_PROVIDER_SNIPPETS.map((snippet) => (
            <div className="onb-install-row" key={snippet.label}>
              <span className="onb-install-label">{snippet.label}</span>
              <span className="mono">{snippet.value}</span>
            </div>
          ))}
        </div>
        <pre style={CODE_STYLE}>{BASE_URL_SNIPPET}</pre>
        <div style={{ marginTop: 10 }}><CopyButton value={BASE_URL_SNIPPET} label="Copy snippet" onCopy={onSnippetViewed} /></div>
      </>
    );
  }

  return (
    <>
      <div className="onb-note">
        The safest start: nothing sits in your request path and no content leaves your boundary. After
        each LLM call, POST token counts and labels. No provider key needed. Optimization needs an
        inline path (SDK or base URL) later.
      </div>
      <pre style={CODE_STYLE}>{METADATA_SNIPPET}</pre>
      <div style={{ marginTop: 10 }}><CopyButton value={METADATA_SNIPPET} label="Copy ingest snippet" onCopy={onSnippetViewed} /></div>
    </>
  );
}

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

function IntegrationHealth({ integration, path }: { integration: OnboardingIntegration; path: IntegrationPath }) {
  const match = integration.providers.find((p) => p.method === path.method);
  const seenMethod = integration.providers.find((p) => p.method !== "none");

  if (path.method === "sdk" && integration.any_sdk) {
    return (
      <div className="pill green" style={{ marginTop: 10 }}>
        Fail-open SDK detected{match?.sdk_client ? ` (${match.sdk_client})` : ""}. You are production-safe.
      </div>
    );
  }
  if (integration.base_url_without_sdk) {
    return (
      <div className="onb-note warn" style={{ marginTop: 10 }}>
        This traffic is running through base-URL mode, which is not fail-open. Before it is
        production-critical, move it to the fail-open SDK so a Varsten outage can never block a request.
      </div>
    );
  }
  if (path.method === "metadata" && seenMethod?.method === "metadata") {
    return (
      <div className="pill green" style={{ marginTop: 10 }}>
        Metadata ingestion is live. Nothing is inline and no content left your boundary.
      </div>
    );
  }
  return null;
}

function ConnectAndVerifyStep({
  status,
  path,
  onBack,
  onSnippetViewed,
  onFinish,
}: {
  status: OnboardingStatus;
  path: IntegrationPath;
  onBack: (() => void) | null;
  onSnippetViewed: () => void;
  onFinish: () => void;
}) {
  const fr = status.first_request;
  const spinnerRef = useRef<HTMLDivElement>(null);

  return (
    <>
      <IntegrationSnippet path={path} onSnippetViewed={onSnippetViewed} />

      <div className="onb-verify">
        {!fr.seen ? (
          <WaitingForFirstRequest spinnerRef={spinnerRef} path={path} />
        ) : (
          <>
            <div className="onb-note pos" style={{ fontWeight: 600 }}>
              {fr.source === "ingest"
                ? "First usage record received. Varsten is measuring your AI traffic."
                : "First request received. Varsten is observing your AI traffic. No production behavior has been changed."}
            </div>
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
            <IntegrationHealth integration={status.integration} path={path} />
            <div className="onb-note" style={{ marginTop: 12 }}>
              As traffic builds, your <strong>Dashboard</strong> fills in live spend and the cuts worth
              real money, and <strong>Proof</strong> starts a verified savings number you can take to
              finance.
            </div>
            {path.method === "sdk" ? <FailOpenSelfTest /> : null}
          </>
        )}
      </div>

      {/* Setup is done once the snippet is in hand — the live request is a
          confirmation, not a gate. The dashboard is always reachable so an SDK
          integration that deploys hours later never sits on a dead-end. */}
      <StepFooter
        onBack={onBack}
        primary={{ label: fr.seen ? "Go to dashboard" : "Finish — go to dashboard", onClick: onFinish }}
      />
    </>
  );
}

function WaitingForFirstRequest({ spinnerRef, path }: { spinnerRef: React.RefObject<HTMLDivElement | null>; path: IntegrationPath }) {
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
        You&apos;re set up. Nothing else to do here.
      </div>
      <div className="onb-waiting-row" style={{ marginTop: 8 }}>
        <div className="spinner" ref={spinnerRef} />
        <span>
          {path.method === "metadata"
            ? "Listening for your first usage record — it appears here live. You can head to the dashboard now."
            : "Listening for your first request — it appears here live. You can head to the dashboard now."}
        </span>
      </div>
      {slow ? (
        <div className="onb-note" style={{ marginTop: 10 }}>
          Nothing yet? That&apos;s fine — traffic can take a while to reach a new integration. If you expected
          it sooner, check that you are using your <span className="mono">vk_</span> Varsten key
          {path.method === "metadata" ? (
            <> and POSTing to <span className="mono">{PROXY_BASE}/usage-events</span>.</>
          ) : (
            <>, the base URL is <span className="mono">{PROXY_BASE}</span>, and the request reached a connected provider.</>
          )}
        </div>
      ) : null}
    </div>
  );
}

function FailOpenSelfTest() {
  return (
    <div style={{ marginTop: 16 }}>
      <div className="onb-note" style={{ fontWeight: 600 }}>Recommended: prove fail-open before you roll out</div>
      <div className="onb-note">
        Point the SDK at a dead port in a non-production shell. The request should still complete
        through your provider and your <span className="mono">onFallback</span> handler should fire.
      </div>
      <pre style={CODE_STYLE}>{SDK_FAILOPEN_TEST}</pre>
      <div style={{ marginTop: 10 }}><CopyButton value={SDK_FAILOPEN_TEST} label="Copy self-test" /></div>
    </div>
  );
}
