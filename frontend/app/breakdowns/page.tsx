"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/components/session";
import { RequireSession } from "@/components/RequireSession";
import { usd, compact } from "@/lib/format";
import type { Breakdown, BreakdownDimension } from "@/lib/types";

const DIMENSIONS: { key: BreakdownDimension; label: string }[] = [
  { key: "provider", label: "Providers" },
  { key: "model", label: "Models" },
  { key: "workflow", label: "Workflows" },
  { key: "external_user_id", label: "Users" },
];

export default function BreakdownsPage() {
  return (
    <RequireSession>
      <Breakdowns />
    </RequireSession>
  );
}

function Breakdowns() {
  const { getToken, activeProjectId } = useSession();
  const [dimension, setDimension] = useState<BreakdownDimension>("provider");
  const [data, setData] = useState<Breakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeProjectId) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const d = await api.breakdown(token, activeProjectId, dimension, { days: 30, limit: 50 });
        if (cancelled) return;
        setData(d);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, activeProjectId, dimension]);

  const total = (data?.rows ?? []).reduce((s, r) => s + parseFloat(r.spend), 0);

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <div className="page-title">Providers & Models</div>
          <div className="page-sub">Spend grouped by dimension, last 30 days.</div>
        </div>
        <div className="spacer" />
        <div style={{ display: "flex", gap: 6 }}>
          {DIMENSIONS.map((d) => (
            <button
              key={d.key}
              className={`btn${dimension === d.key ? " primary" : ""}`}
              onClick={() => {
                if (d.key !== dimension) {
                  setLoading(true);
                  setDimension(d.key);
                }
              }}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        {error ? (
          <div className="empty"><div className="et">Could not load breakdown</div><div className="es">{error}</div></div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>{DIMENSIONS.find((d) => d.key === dimension)?.label.replace(/s$/, "")}</th>
                <th className="r">Requests</th>
                <th className="r">Input tokens</th>
                <th className="r">Output tokens</th>
                <th className="r">Spend</th>
                <th className="r">Share</th>
              </tr>
            </thead>
            <tbody>
              {(data?.rows ?? []).map((r, i) => {
                const spend = parseFloat(r.spend);
                return (
                  <tr key={i}>
                    <td className="name">{r.key ?? "(none)"}</td>
                    <td className="r mono tnum">{r.requests.toLocaleString()}</td>
                    <td className="r mono tnum muted">{compact(r.input_tokens)}</td>
                    <td className="r mono tnum muted">{compact(r.output_tokens)}</td>
                    <td className="r mono tnum">{usd(spend, 4)}</td>
                    <td className="r mono tnum muted">{total ? ((spend / total) * 100).toFixed(1) + "%" : "—"}</td>
                  </tr>
                );
              })}
              {!loading && (data?.rows.length ?? 0) === 0 && (
                <tr><td colSpan={6} className="muted" style={{ textAlign: "center", padding: 28 }}>No usage in this window.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
