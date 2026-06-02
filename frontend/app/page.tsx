"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/api";
import { useSession } from "@/components/session";
import { RequireSession } from "@/components/RequireSession";
import { SpendLineChart, HBars, type HBarItem } from "@/components/charts";
import { usd, compact, relativeTime } from "@/lib/format";
import type {
  Breakdown,
  MetricsOverview,
  SpendTrend,
  UsageEventPage,
} from "@/lib/types";

const PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

function toBars(b: Breakdown | null): HBarItem[] {
  if (!b) return [];
  return b.rows.map((r, i) => ({
    name: r.key ?? "(none)",
    value: parseFloat(r.spend),
    color: PALETTE[i % PALETTE.length],
  }));
}

export default function OverviewPage() {
  return (
    <RequireSession>
      <Overview />
    </RequireSession>
  );
}

function Overview() {
  const { getToken, activeProjectId } = useSession();
  const [overview, setOverview] = useState<MetricsOverview | null>(null);
  const [trend, setTrend] = useState<SpendTrend | null>(null);
  const [models, setModels] = useState<Breakdown | null>(null);
  const [providers, setProviders] = useState<Breakdown | null>(null);
  const [recent, setRecent] = useState<UsageEventPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeProjectId) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const [o, t, m, p, r] = await Promise.all([
          api.overview(token, activeProjectId),
          api.spendTrend(token, activeProjectId, 30),
          api.breakdown(token, activeProjectId, "model", { limit: 5 }),
          api.breakdown(token, activeProjectId, "provider", { limit: 6 }),
          api.usageEvents(token, activeProjectId, { limit: 8 }),
        ]);
        if (cancelled) return;
        setOverview(o);
        setTrend(t);
        setModels(m);
        setProviders(p);
        setRecent(r);
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
  }, [activeProjectId, getToken]);

  if (loading) {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 300 }}>
        <div className="spinner" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="view">
        <div className="empty">
          <div className="et">Could not load metrics</div>
          <div className="es">{error}</div>
        </div>
      </div>
    );
  }

  const avg = overview?.avg_cost_per_request_today;

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <div className="page-title">Overview</div>
          <div className="page-sub">AI spend and usage across your project.</div>
        </div>
      </div>

      <div className="grid kpi-row">
        <Kpi label="Spend today" value={usd(overview?.spend_today ?? 0)} foot={`${overview?.requests_today ?? 0} requests`} />
        <Kpi label="Spend this month" value={usd(overview?.spend_month ?? 0)} foot={`${overview?.requests_month ?? 0} requests`} />
        <Kpi
          label="Tokens today"
          value={compact((overview?.input_tokens_today ?? 0) + (overview?.output_tokens_today ?? 0))}
          foot={`${compact(overview?.input_tokens_today ?? 0)} in · ${compact(overview?.output_tokens_today ?? 0)} out`}
        />
        <Kpi label="Avg cost / request" value={avg ? usd(avg, 4) : "—"} foot="today" />
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head">
            <h3>Spend trend</h3>
            <span className="sub">last 30 days</span>
          </div>
          <SpendLineChart points={trend?.points ?? []} />
        </div>
        <div className="card">
          <div className="card-head">
            <h3>Top providers</h3>
            <span className="sub">by spend</span>
          </div>
          <div style={{ padding: "6px 0" }}>
            <HBars items={toBars(providers)} />
          </div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-head">
            <h3>Recent usage</h3>
            <div className="right">
              <Link href="/explorer" className="btn">Open explorer</Link>
            </div>
          </div>
          <table className="tbl">
            <thead>
              <tr>
                <th>Model</th>
                <th>Workflow</th>
                <th className="r">Cost</th>
                <th className="r">Received</th>
              </tr>
            </thead>
            <tbody>
              {(recent?.items ?? []).map((e) => (
                <tr key={e.id}>
                  <td>
                    <div className="name">
                      <span className="dot-ic" style={{ background: "var(--accent)" }} />
                      {e.model}
                    </div>
                    <span className="muted" style={{ fontSize: 11.5 }}>{e.provider}</span>
                  </td>
                  <td className="muted">{e.workflow ?? "—"}</td>
                  <td className="r mono tnum">{usd(e.cost_usd, 4)}</td>
                  <td className="r muted">{relativeTime(e.received_at)}</td>
                </tr>
              ))}
              {(recent?.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={4} className="muted" style={{ textAlign: "center", padding: 28 }}>
                    No usage yet. Send your first event from Setup.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="card-head">
            <h3>Top models</h3>
            <span className="sub">by spend</span>
          </div>
          <div style={{ padding: "6px 0" }}>
            <HBars items={toBars(models)} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value, foot }: { label: string; value: string; foot: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value mono tnum">{value}</div>
      <div className="foot">{foot}</div>
    </div>
  );
}
