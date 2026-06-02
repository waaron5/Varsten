"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApiKey } from "@/components/providers";
import { useSession } from "@/components/session";
import { RequireSession } from "@/components/RequireSession";
import { relativeTime } from "@/lib/format";
import type { ApiKeySummary } from "@/lib/types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function SetupPage() {
  return (
    <RequireSession>
      <Setup />
    </RequireSession>
  );
}

function Setup() {
  const { getToken, activeProjectId, projects } = useSession();
  const { apiKey, setApiKey } = useApiKey();
  const [keys, setKeys] = useState<ApiKeySummary[]>([]);
  const [generated, setGenerated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeProject = projects.find((p) => p.id === activeProjectId);

  const loadKeys = useCallback(async () => {
    if (!activeProjectId) return;
    const token = await getToken();
    setKeys(await api.listApiKeys(token, activeProjectId));
  }, [getToken, activeProjectId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadKeys();
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadKeys]);

  const generate = async () => {
    if (!activeProjectId) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      const created = await api.createApiKey(token, activeProjectId, "ingest-key");
      setGenerated(created.plaintext_key);
      setApiKey(created.plaintext_key); // powers the curl snippet + waiting status
      await loadKeys();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    try {
      const token = await getToken();
      await api.revokeApiKey(token, id);
      await loadKeys();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
    }
  };

  const active = keys.filter((k) => !k.revoked_at);

  return (
    <div className="view" style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <div className="page-title">Setup</div>
          <div className="page-sub">
            Generate an API key for <b>{activeProject?.name ?? "your project"}</b> and send your first usage event.
          </div>
        </div>
      </div>

      {error && (
        <div className="card card-pad" style={{ marginBottom: 16, color: "var(--neg)" }}>{error}</div>
      )}

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
          <h3 style={{ fontSize: 14 }}>1. API keys</h3>
          <button className="btn primary" style={{ marginLeft: "auto" }} disabled={busy} onClick={generate}>
            {busy ? "Generating…" : "Generate key"}
          </button>
        </div>
        <p className="page-sub" style={{ marginBottom: 14 }}>
          A key authenticates usage events sent to this project. You paste it into your own app — the one calling OpenAI, Claude, etc.
        </p>

        {generated && (
          <div
            className="card-pad"
            style={{
              border: "1px solid var(--accent-line)",
              background: "var(--accent-soft)",
              borderRadius: "var(--radius)",
              marginBottom: 14,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
              Copy your key now — it will not be shown again.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <code className="mono" style={{ flex: 1, wordBreak: "break-all" }}>{generated}</code>
              <button className="btn" onClick={() => navigator.clipboard.writeText(generated)}>Copy</button>
            </div>
          </div>
        )}

        {active.length > 0 ? (
          <table className="tbl" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Prefix</th>
                <th>Created</th>
                <th>Last used</th>
                <th className="r"></th>
              </tr>
            </thead>
            <tbody>
              {active.map((k) => (
                <tr key={k.id}>
                  <td className="name">{k.name}</td>
                  <td className="mono muted">{k.key_prefix}…</td>
                  <td className="muted">{relativeTime(k.created_at)}</td>
                  <td className="muted">{k.last_used_at ? relativeTime(k.last_used_at) : "never"}</td>
                  <td className="r">
                    <button className="btn" onClick={() => revoke(k.id)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-hint">No active keys yet. Generate one to get started.</div>
        )}
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, marginBottom: 4 }}>2. Send a usage event</h3>
        <p className="page-sub" style={{ marginBottom: 14 }}>
          Run this from any terminal or service. The event lands in this project and shows up below within seconds.
        </p>
        <CurlSnippet apiKey={apiKey} />
      </div>

      <WaitingStatus />
    </div>
  );
}

function CurlSnippet({ apiKey }: { apiKey: string | null }) {
  const key = apiKey ?? "vk_generate_a_key_above";
  const snippet = `curl -X POST ${BASE}/v1/usage-events \\
  -H "authorization: Bearer ${key}" \\
  -H "content-type: application/json" \\
  -d '{
    "provider": "openai",
    "model": "gpt-4o-mini",
    "operation": "chat_completion",
    "external_user_id": "user_123",
    "workflow": "support_agent",
    "input_tokens": 1200,
    "output_tokens": 340,
    "cost_usd": 0.0021,
    "metadata": { "environment": "production" }
  }'`;
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <button
          className="btn"
          onClick={() => {
            navigator.clipboard.writeText(snippet);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="code">{snippet}</div>
    </div>
  );
}

function WaitingStatus() {
  const { apiKey } = useApiKey();
  const [count, setCount] = useState<number | null>(null);
  const [latest, setLatest] = useState<string | null>(null);
  const seen = useRef(false);

  useEffect(() => {
    if (!apiKey) return;
    let cancelled = false;
    const poll = async () => {
      try {
        // API-key auth: project is implied by the key, so no project_id.
        const page = await api.usageEvents(apiKey, undefined, { limit: 1 });
        if (cancelled) return;
        setCount(page.items.length);
        if (page.items[0]) {
          setLatest(page.items[0].received_at);
          seen.current = true;
        }
      } catch {
        // ignore transient errors during polling
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [apiKey]);

  if (!apiKey) return null;

  const received = count !== null && count > 0;
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {received ? (
          <span className="pill green">
            <span className="dotp" style={{ background: "var(--pos)" }} />
            Receiving events
          </span>
        ) : (
          <span className="pill amber">
            <span className="dotp" style={{ background: "var(--warn)" }} />
            Waiting for first event…
          </span>
        )}
        <span className="page-sub" style={{ margin: 0 }}>
          {received
            ? `Latest event ${latest ? new Date(latest).toLocaleString() : ""}`
            : "Polling every 3s. Run the curl command above."}
        </span>
      </div>
    </div>
  );
}
