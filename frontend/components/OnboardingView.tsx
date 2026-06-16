"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import { useSession } from "@/components/session";
import { api } from "@/lib/api";
import type { ApiKeyCreated, OnboardingStatus } from "@/lib/types";

// The public proxy base customers point their SDK at (distinct from the dashboard
// API host). Documented value; swap per environment if the proxy host differs.
const PROXY_BASE = "https://api.varsten.ai/v1";
const SETUP_CALL_HREF = "mailto:mail@varsten.ai?subject=Varsten%20setup%20call";
const DOCS_HREF = "https://varsten.ai/docs";

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
  const { data, loading, error, reload } = useProjectResource<OnboardingStatus>(api.onboardingStatus);

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
    router.push("/command-center");
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
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="card-head">
          <h3>Connect Varsten</h3>
          <div className="right"><span className="pill neutral">Observe-only</span></div>
        </div>
        <div className="es" style={{ padding: "0 12px 12px" }}>
          Send your AI traffic through Varsten to see spend, tokens, latency, and savings
          opportunities. Varsten is observing only — no production behavior is changed until you
          enable Performance.
        </div>
      </div>

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
      {created ? (
        <>
          <div className="es" style={{ color: "var(--pos, #1a7f37)", marginTop: 8 }}>
            Copy this now — you won&apos;t be able to see it again.
          </div>
          <pre style={CODE_STYLE}>{created.plaintext_key}</pre>
          <CopyButton value={created.plaintext_key} label="Copy key" />
        </>
      ) : status.has_api_key ? (
        <div className="es" style={{ marginTop: 8 }}>
          A key already exists for this project. Create a new one only if you need to (the old key
          keeps working).
          <div style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy} onClick={() => void create()}>
              {busy ? "Creating…" : "Create another key"}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={busy || !activeProjectId} onClick={() => void create()}>
            {busy ? "Creating…" : "Create API key"}
          </button>
        </div>
      )}
      {err && <div className="es" style={{ color: "var(--neg)" }}>{err}</div>}
    </StepCard>
  );
}

function ProviderStep({ status, onChanged }: { status: OnboardingStatus; onChanged: () => void }) {
  const { activeProjectId, getToken } = useSession();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const openai = status.provider_connections.find((c) => c.provider === "openai");
  const connected = openai?.status === "connected";

  const connect = async () => {
    if (!activeProjectId || !key.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.upsertProviderConnection(await getToken(), activeProjectId, "openai", key.trim());
      setKey("");
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <StepCard n={2} title="Connect your OpenAI key" done={connected}>
      <div className="es">
        Varsten forwards your requests to OpenAI using this key. It is stored encrypted and never
        shown back to you. We only ever return status — never your key.
      </div>
      {connected ? (
        <div className="es" style={{ color: "var(--pos, #1a7f37)", marginTop: 8 }}>
          OpenAI connected{openai?.last_verified_at ? ` · verified ${new Date(openai.last_verified_at).toLocaleString()}` : ""}.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input
            className="input"
            type="password"
            placeholder="sk-…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="btn primary" disabled={busy || !key.trim()} onClick={() => void connect()}>
            {busy ? "Connecting…" : "Connect"}
          </button>
        </div>
      )}
      {err && (
        <div className="es" style={{ color: "var(--neg)", marginTop: 8 }}>
          {err}
          <div style={{ marginTop: 6 }}>
            If provider key storage is not yet available in your environment, <a href={SETUP_CALL_HREF}>book a setup call</a> and we&apos;ll finish the connection with you.
          </div>
        </div>
      )}
      {openai?.last_error && !err && (
        <div className="es" style={{ color: "var(--neg)", marginTop: 8 }}>Last error: {openai.last_error}</div>
      )}
    </StepCard>
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

function IntegrateStep() {
  return (
    <StepCard n={3} title="Point your code at Varsten" done={false}>
      <div className="es">Swap your OpenAI base URL for Varsten and use your Varsten key. That&apos;s the whole integration.</div>
      <pre style={CODE_STYLE}>{SNIPPET_TS}</pre>
      <CopyButton value={SNIPPET_TS} label="Copy snippet" />
      <div className="es" style={{ marginTop: 12 }}>
        Optional but recommended: label requests so Varsten can break spend and savings down by
        workflow, task, customer, and team.
      </div>
      <pre style={CODE_STYLE}>{SNIPPET_METADATA}</pre>
      <CopyButton value={SNIPPET_METADATA} label="Copy with metadata" />
      <div className="es" style={{ marginTop: 8 }}>
        Anthropic and Gemini are supported via the same proxy. Other SDKs: use the OpenAI-compatible
        endpoint above, or <a href={SETUP_CALL_HREF}>contact us</a>.
      </div>
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
