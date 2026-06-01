"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApiKey } from "@/components/providers";
import { RequireKey } from "@/components/RequireKey";
import { usd, relativeTime } from "@/lib/format";
import type { UsageEvent, UsageEventFilters, UsageEventPage } from "@/lib/types";

const PAGE_SIZE = 25;

type StringFilterKey = "provider" | "model" | "workflow" | "external_user_id";

const FILTER_FIELDS: { key: StringFilterKey; label: string }[] = [
  { key: "provider", label: "Provider" },
  { key: "model", label: "Model" },
  { key: "workflow", label: "Workflow" },
  { key: "external_user_id", label: "User ID" },
];

export default function ExplorerPage() {
  return (
    <RequireKey>
      <Explorer />
    </RequireKey>
  );
}

function Explorer() {
  const { apiKey } = useApiKey();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<UsageEventFilters>({});
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<UsageEventPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<UsageEvent | null>(null);

  const load = useCallback(() => {
    if (!apiKey) return;
    api
      .usageEvents(apiKey, { ...filters, limit: PAGE_SIZE, offset })
      .then((p) => {
        setPage(p);
        setError(null);
      })
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)),
      )
      .finally(() => setLoading(false));
  }, [apiKey, filters, offset]);

  useEffect(load, [load]);

  const applyFilters = () => {
    const clean: UsageEventFilters = {};
    for (const { key } of FILTER_FIELDS) {
      const v = draft[key]?.trim();
      if (v) clean[key] = v;
    }
    setLoading(true);
    setOffset(0);
    setFilters(clean);
  };

  const clearFilters = () => {
    setLoading(true);
    setDraft({});
    setOffset(0);
    setFilters({});
  };

  const goToOffset = (next: number) => {
    setLoading(true);
    setOffset(next);
  };

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <div className="page-title">Usage Explorer</div>
          <div className="page-sub">Filter raw usage records and inspect any event.</div>
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          {FILTER_FIELDS.map((f) => (
            <div key={f.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label className="page-sub" style={{ margin: 0, fontSize: 11.5 }}>{f.label}</label>
              <input
                className="input"
                value={draft[f.key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                onKeyDown={(e) => e.key === "Enter" && applyFilters()}
                placeholder="any"
                style={{ width: 150 }}
              />
            </div>
          ))}
          <button className="btn primary" onClick={applyFilters}>Apply</button>
          <button className="btn" onClick={clearFilters}>Clear</button>
        </div>
      </div>

      <div className="card">
        {error ? (
          <div className="empty"><div className="et">Could not load events</div><div className="es">{error}</div></div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Operation</th>
                <th>Workflow</th>
                <th>User</th>
                <th className="r">Tokens</th>
                <th className="r">Cost</th>
                <th className="r">Received</th>
              </tr>
            </thead>
            <tbody>
              {(page?.items ?? []).map((e) => (
                <tr key={e.id} className="clickable" onClick={() => setSelected(e)}>
                  <td className="muted">{e.provider}</td>
                  <td className="name">{e.model}</td>
                  <td className="muted">{e.operation}</td>
                  <td className="muted">{e.workflow ?? "—"}</td>
                  <td className="muted">{e.external_user_id ?? "—"}</td>
                  <td className="r mono tnum">{e.total_tokens.toLocaleString()}</td>
                  <td className="r mono tnum">{usd(e.cost_usd, 4)}</td>
                  <td className="r muted">{relativeTime(e.received_at)}</td>
                </tr>
              ))}
              {!loading && (page?.items.length ?? 0) === 0 && (
                <tr><td colSpan={8} className="muted" style={{ textAlign: "center", padding: 28 }}>No events match these filters.</td></tr>
              )}
            </tbody>
          </table>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
          <span className="page-sub" style={{ margin: 0 }}>
            {loading ? "Loading…" : `Showing ${page?.items.length ?? 0} · offset ${offset}`}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button className="btn" disabled={offset === 0} onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
            <button className="btn" disabled={!page?.has_more} onClick={() => goToOffset(offset + PAGE_SIZE)}>Next</button>
          </div>
        </div>
      </div>

      {selected && <DetailDrawer event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function DetailDrawer({ event, onClose }: { event: UsageEvent; onClose: () => void }) {
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-head">
          <h3 style={{ fontSize: 14 }}>Usage event</h3>
          <button className="btn" style={{ marginLeft: "auto" }} onClick={onClose}>Close</button>
        </div>
        <div className="drawer-body">
          <div className="code">{JSON.stringify(event, null, 2)}</div>
        </div>
      </div>
    </>
  );
}
