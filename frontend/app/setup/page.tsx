"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApiKey } from "@/components/providers";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function SetupPage() {
  const { apiKey, ready, setApiKey, clearApiKey } = useApiKey();
  const [draft, setDraft] = useState("");

  if (!ready) {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div className="view" style={{ maxWidth: 820 }}>
      <div className="page-head">
        <div>
          <div className="page-title">Setup</div>
          <div className="page-sub">Connect a project key and send your first usage event.</div>
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, marginBottom: 4 }}>1. Connect your project key</h3>
        <p className="page-sub" style={{ marginBottom: 14 }}>
          Generate a key for your project, then paste it here. It is stored only in this browser.
        </p>
        {apiKey ? (
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="pill green">
              <span className="dotp" style={{ background: "var(--pos)" }} />
              Connected · {apiKey.slice(0, 7)}…
            </span>
            <button className="btn" onClick={() => clearApiKey()}>
              Disconnect
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              style={{ flex: 1 }}
              placeholder="vk_..."
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button className="btn primary" disabled={!draft.trim()} onClick={() => setApiKey(draft.trim())}>
              Connect
            </button>
          </div>
        )}
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, marginBottom: 4 }}>2. Send a usage event</h3>
        <p className="page-sub" style={{ marginBottom: 14 }}>
          Run this from any service. The event lands in your project and shows up below within seconds.
        </p>
        <CurlSnippet apiKey={apiKey} />
      </div>

      <WaitingStatus />
    </div>
  );
}

function CurlSnippet({ apiKey }: { apiKey: string | null }) {
  const key = apiKey ?? "vk_your_key_here";
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
        const page = await api.usageEvents(apiKey, { limit: 1 });
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
