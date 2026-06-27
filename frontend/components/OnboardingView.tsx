"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { NoticeCard } from "@/components/viewPrimitives";
import { useProjectResource } from "@/components/useProjectResource";
import { useSession } from "@/components/session";
import { ApiError, api } from "@/lib/api";
import type { ApiKeyCreated, OnboardingStatus } from "@/lib/types";

// The public proxy base customers point their SDK at (distinct from the dashboard
// API host). Documented value; swap per environment if the proxy host differs.
const PROXY_BASE = "https://api.varsten.ai/v1";
const SETUP_CALL_HREF = "mailto:mail@varsten.ai?subject=Varsten%20setup%20call";
const DOCS_HREF = "https://varsten.ai/docs";
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
  margin: "8px 0",
};

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
  // soon as it arrives so we are not hammering the API on a finished workspace.
  useEffect(() => {
    if (!data || firstSeen) return;
    const id = window.setInterval(() => {
      void reload();
    }, 4000);
    return () => window.clearInterval(id);
  }, [data, firstSeen, reload]);

  const finish = useCallback(async () => {
    try {
      await api.completeOnboarding(await getToken(), activeProjectId ?? undefined);
    } catch {
      // Completion is best-effort; the dashboard still works if it fails.
    }
    router.push("/dashboard");
  }, [activeProjectId, getToken, router]);

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
    <div className="view" style={{ maxWidth: 860 }}>
      <NoticeCard badge="Observe-only" title="Connect Varsten" style={{ marginBottom: 12 }}>
        Send your AI traffic through Varsten to see spend, tokens, latency, and savings
        opportunities. Varsten is observing only — no production behavior is changed until you
        enable Performance.
      </NoticeCard>

      <ApiKeyStep status={data} />
      <ProviderStep status={data} onChanged={() => void reload()} />
      <IntegrateStep />
      <TestStep status={data} />

      <div className="empty-actions" style={{ marginTop: 16 }}>
        <button className="btn primary" disabled={!firstSeen} onClick={() => void finish()}>
          {firstSeen ? "Continue to dashboard" : "Waiting for your first request…"}
        </button>
        <a className="btn" href={DOCS_HREF} target="_blank" rel="noreferrer">View docs</a>
        <a className="btn" href={SETUP_CALL_HREF}>Book setup call</a>
      </div>
    </div>
  );
}

function StepCard({ n, title, done, children }: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="card-head">
        <h3>
          <span className="pill" style={{ marginRight: 8 }}>{done ? "✓" : n}</span>
          {title}
        </h3>
        <div className="right">
          <span className={`pill ${done ? "green" : "neutral"}`}>{done ? "Done" : "To do"}</span>
        </div>
      </div>
      <div style={{ padding: "0 12px 12px" }}>{children}</div>
    </div>
  );
}

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
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
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

function ApiKeyStep({ status }: { status: OnboardingStatus }) {
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

  return (
    <StepCard n={1} title="Get your Varsten API key" done={status.has_api_key || created !== null}>
      <div className="es">
        This is your Varsten key. Use it in place of your provider key when calling Varsten.
      </div>
      <ApiKeyStepContent
        activeProjectId={activeProjectId}
        busy={busy}
        created={created}
        hasApiKey={status.has_api_key}
        onCreate={create}
      />
      {err && <div className="es" style={{ color: "var(--neg)" }}>{err}</div>}
    </StepCard>
  );
}

function ApiKeyStepContent({
  activeProjectId,
  busy,
  created,
  hasApiKey,
  onCreate,
}: {
  activeProjectId: string | null;
  busy: boolean;
  created: ApiKeyCreated | null;
  hasApiKey: boolean;
  onCreate: () => Promise<void>;
}) {
  if (created) return <CreatedApiKey created={created} />;
  if (hasApiKey) return <ExistingApiKey busy={busy} onCreate={onCreate} />;
  return (
    <div style={{ marginTop: 8 }}>
      <button className="btn primary" disabled={busy || !activeProjectId} onClick={() => void onCreate()}>
        {busy ? "Creating…" : "Create API key"}
      </button>
    </div>
  );
}

function CreatedApiKey({ created }: { created: ApiKeyCreated }) {
  return (
    <>
      <div className="es" style={{ color: "var(--pos, #1a7f37)", marginTop: 8 }}>
        Copy this now — you won&apos;t be able to see it again.
      </div>
      <pre style={CODE_STYLE}>{created.plaintext_key}</pre>
      <CopyButton value={created.plaintext_key} label="Copy key" />
    </>
  );
}

function ExistingApiKey({ busy, onCreate }: { busy: boolean; onCreate: () => Promise<void> }) {
  return (
    <div className="es" style={{ marginTop: 8 }}>
      A key already exists for this project. Create a new one only if you need to (the old key
      keeps working).
      <div style={{ marginTop: 8 }}>
        <button className="btn" disabled={busy} onClick={() => void onCreate()}>
          {busy ? "Creating…" : "Create another key"}
        </button>
      </div>
    </div>
  );
}

function ProviderStep({ status, onChanged }: { status: OnboardingStatus; onChanged: () => void }) {
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
    <StepCard n={2} title="Connect your provider key" done={status.has_provider_connection}>
      <div className="es">
        Choose the provider your app already uses. Varsten validates the key, stores it through the configured vault, and only returns connection status.
      </div>
      <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
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
      {manualSetup && (
        <div className="modal-backdrop" role="presentation" onClick={() => setManualSetup(null)}>
          <div className="modal-card" role="dialog" aria-modal="true" aria-label="Manual provider setup" onClick={(e) => e.stopPropagation()}>
            <div className="card-head">
              <h3>Manual setup required</h3>
              <button className="btn" onClick={() => setManualSetup(null)}>Close</button>
            </div>
            <div style={{ padding: "0 12px 12px" }}>
              <div className="es">
                This environment cannot store {manualSetup.provider} keys from the dashboard yet. Your traffic is not affected; a Varsten operator needs to finish vault setup.
              </div>
              <div className="es" style={{ color: "var(--text-2)", marginTop: 8 }}>{manualSetup.message}</div>
              <div className="empty-actions" style={{ justifyContent: "flex-start", marginTop: 12 }}>
                <a className="btn primary" href={SETUP_CALL_HREF}>Book setup call</a>
              </div>
            </div>
          </div>
        </div>
      )}
    </StepCard>
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
    <div className="card" style={{ boxShadow: "none", margin: 0 }}>
      <div className="card-head">
        <h3>{provider.name}</h3>
        <div className="right">
          <span className={`pill ${connected ? "green" : "neutral"}`}>
            {providerConnectionLabel(connection)}
          </span>
        </div>
      </div>
      <div style={{ padding: "0 12px 12px" }}>
        <div className="es">{provider.description}</div>
        <div className="es mono" style={{ marginTop: 6 }}>{provider.endpoint}</div>
        {connected ? (
          <ConnectedProvider connection={connection} />
        ) : (
          <ProviderKeyForm busy={busy} onConnect={onConnect} onKeyChange={onKeyChange} provider={provider} value={value} />
        )}
        {error && !connected ? (
          <div className="es" style={{ color: "var(--neg)", marginTop: 8 }}>{error}</div>
        ) : null}
      </div>
    </div>
  );
}

function ConnectedProvider({ connection }: { connection: ProviderConnectionStatus | undefined }) {
  const verifiedAt = connection?.last_verified_at ? ` ${new Date(connection.last_verified_at).toLocaleString()}` : "";
  return (
    <div className="es" style={{ color: "var(--pos)", marginTop: 8 }}>
      Verified{verifiedAt}.
    </div>
  );
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
    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
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

const SNIPPET_TS = `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "${PROXY_BASE}",
});`;

const SNIPPET_METADATA = `const response = await fetch("${PROXY_BASE}/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.VARSTEN_API_KEY}\`,
    "Content-Type": "application/json",
    "X-Varsten-Metadata": JSON.stringify({
      feature: "support_reply",
      workflow: "billing_support",
      task_type: "support_reply.billing",
      risk_level: "medium",
      environment: "production"
    })
  },
  body: JSON.stringify({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "Say hello from Varsten" }]
  })
});`;

const PROVIDER_SNIPPETS = [
  { label: "OpenAI", value: `baseURL: "${PROXY_BASE}"` },
  { label: "Anthropic", value: `baseURL: "${PROXY_BASE}"` },
  { label: "Gemini", value: `baseURL: "${PROXY_BASE}/v1beta"` },
];

function IntegrateStep() {
  return (
    <StepCard n={3} title="Point your code at Varsten" done={false}>
      <div className="es">Swap your provider base URL for Varsten and use your Varsten key. Your provider key stays in the Varsten vault.</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, marginTop: 8 }}>
        {PROVIDER_SNIPPETS.map((snippet) => (
          <div className="card" key={snippet.label} style={{ boxShadow: "none", margin: 0, padding: 12 }}>
            <div className="es" style={{ fontWeight: 700 }}>{snippet.label}</div>
            <div className="es mono" style={{ marginTop: 4 }}>{snippet.value}</div>
          </div>
        ))}
      </div>
      <pre style={CODE_STYLE}>{SNIPPET_TS}</pre>
      <CopyButton value={SNIPPET_TS} label="Copy snippet" />
      <div className="es" style={{ marginTop: 12 }}>
        Optional but recommended: label requests so Varsten can break spend and savings down by
        workflow, task, customer, and team.
      </div>
      <pre style={CODE_STYLE}>{SNIPPET_METADATA}</pre>
      <CopyButton value={SNIPPET_METADATA} label="Copy with metadata" />
    </StepCard>
  );
}

function fmtUsd(v?: string | null): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `$${n.toFixed(6)}` : "—";
}

function TestStep({ status }: { status: OnboardingStatus }) {
  const fr = status.first_request;
  const spinnerRef = useRef<HTMLDivElement>(null);

  return (
    <StepCard n={4} title="Send a test request" done={fr.seen}>
      {!fr.seen ? (
        <div className="es">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="spinner" ref={spinnerRef} />
            Waiting for your first request… run the snippet above and it will appear here.
          </div>
        </div>
      ) : (
        <>
          <div className="es" style={{ color: "var(--pos, #1a7f37)", fontWeight: 600 }}>
            First request received. Varsten is observing your AI traffic. No production behavior has been changed.
          </div>
          <table className="tbl" style={{ marginTop: 10 }}>
            <tbody>
              <tr><td className="muted">Provider</td><td>{fr.provider}</td></tr>
              <tr><td className="muted">Model</td><td>{fr.model}</td></tr>
              <tr><td className="muted">Estimated cost</td><td>{fmtUsd(fr.cost_usd)} <span className="muted">({fr.pricing_status})</span></td></tr>
              <tr><td className="muted">Tokens</td><td>{fr.input_tokens} in / {fr.output_tokens} out</td></tr>
              <tr><td className="muted">Latency</td><td>{fr.latency_ms ?? "—"} ms</td></tr>
              <tr><td className="muted">Environment</td><td>{fr.environment ?? "—"}</td></tr>
              <tr><td className="muted">Request id</td><td>{fr.request_id ?? "—"}</td></tr>
              <tr><td className="muted">Task / workflow</td><td>{fr.task_type ?? fr.workflow ?? fr.feature ?? "—"}</td></tr>
            </tbody>
          </table>
          <div className={`pill ${fr.metadata_quality.level === "great" ? "green" : "neutral"}`} style={{ marginTop: 10 }}>
            {fr.metadata_quality.message}
          </div>
        </>
      )}
    </StepCard>
  );
}
