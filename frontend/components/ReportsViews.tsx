"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RequireSession } from "@/components/RequireSession";
import { useSession } from "@/components/session";
import { api } from "@/lib/api";
import { compact, usd } from "@/lib/format";
import type { MonthlyReport } from "@/lib/types";

function titleize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function numberValue(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function percent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${Math.round(n * 100)}%`;
}

function periodLabel(report: MonthlyReport): string {
  return new Date(report.period_start).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function shareHref(report: MonthlyReport): string {
  if (typeof window === "undefined") return `/reports/${report.share_token}`;
  return `${window.location.origin}/reports/${report.share_token}`;
}

function PageState({ loading, error, empty, emptyDetail }: { loading?: boolean; error?: string | null; empty?: string; emptyDetail?: string }) {
  if (loading) return <div className="empty"><div className="spinner" /></div>;
  if (error) {
    return <div className="empty"><div className="et">Could not load report data</div><div className="es">{error}</div></div>;
  }
  if (empty) {
    return <div className="empty"><div className="et">{empty}</div>{emptyDetail ? <div className="es">{emptyDetail}</div> : null}</div>;
  }
  return null;
}

function useDeferredLoad(load: () => Promise<void>) {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
}

function ReportSnapshot({ report }: { report: MonthlyReport }) {
  const savingsRate = numberValue(report.counterfactual_spend_usd) > 0
    ? numberValue(report.gross_savings_usd) / numberValue(report.counterfactual_spend_usd)
    : null;
  return (
    <>
      <div className="grid kpi-row">
        <div className="card kpi">
          <div className="label">Gross saved</div>
          <div className="value">{usd(report.gross_savings_usd, 0)}</div>
          <div className="foot">{savingsRate === null ? "baseline unavailable" : `${percent(savingsRate)} below counterfactual`}</div>
        </div>
        <div className="card kpi">
          <div className="label">Net to customer</div>
          <div className="value">{usd(report.net_savings_usd, 0)}</div>
          <div className="foot">after {usd(report.varsten_fee_usd, 0)} Varsten fee</div>
        </div>
        <div className="card kpi">
          <div className="label">Measured requests</div>
          <div className="value">{compact(report.requests_month)}</div>
          <div className="foot">{report.unpriced_event_count} unpriced events</div>
        </div>
        <div className="card kpi">
          <div className="label">Trust score</div>
          <div className="value">{percent(report.trust_score)}</div>
          <div className="foot">{report.priced_event_count} priced events</div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h3>Attribution</h3></div>
          {report.attribution_rows.length === 0 ? (
            <PageState empty="No attributed savings yet" emptyDetail="Apply engine actions to build lever-level proof." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Lever</th><th>Method</th><th className="r">Actions</th><th className="r">Net saved</th></tr></thead>
              <tbody>
                {report.attribution_rows.map((row) => (
                  <tr key={`${row.lever}-${row.measurement_method}`}>
                    <td>{row.lever ? titleize(row.lever) : "General"}</td>
                    <td className="muted">{titleize(row.measurement_method)}</td>
                    <td className="r">{row.actions}</td>
                    <td className="r">{usd(row.net_savings_usd, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Open opportunities</h3></div>
          {report.top_recommendations.length === 0 ? (
            <PageState empty="No open opportunities" emptyDetail="The executive report is clean for this period." />
          ) : (
            <div className="action-list">
              {report.top_recommendations.map((rec) => (
                <div className="action-row" key={rec.id}>
                  <span className="step-dot" />
                  <div className="action-body">
                    <div className="action-title"><b>{rec.title}</b><span>{rec.estimated_monthly_savings_usd === null ? "Needs pricing" : usd(rec.estimated_monthly_savings_usd, 0)}</span></div>
                    <div className="action-detail">{rec.lever ? titleize(rec.lever) : "General"} · {titleize(rec.risk_level)} risk · {percent(rec.confidence)} confidence</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export function ReportsView() {
  return <RequireSession><ReportsBody /></RequireSession>;
}

function ReportsBody() {
  const { activeProjectId, getToken } = useSession();
  const [reports, setReports] = useState<MonthlyReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = reports[0] ?? null;
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReports(await api.reports(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken]);
  useDeferredLoad(load);
  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await api.createReport(await getToken(), activeProjectId ?? undefined);
      setReports((current) => [report, ...current.filter((item) => item.id !== report.id)]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const shareUrl = useMemo(() => (latest ? shareHref(latest) : ""), [latest]);
  return (
    <div className="view">
      <div className="page-head">
        <div>
          <div className="eyebrow">Reports</div>
          <h1 className="page-title">Executive Report</h1>
          <div className="page-sub">A stable, shareable monthly view of savings, trust, and open opportunities.</div>
        </div>
        <div className="spacer" />
        <button className="btn primary" disabled={busy} onClick={generate} type="button">{busy ? "Generating..." : "Generate current month"}</button>
      </div>

      {loading || error ? (
        <div className="card"><PageState loading={loading} error={error} /></div>
      ) : !latest ? (
        <div className="card"><PageState empty="No reports yet" emptyDetail="Generate the current month report to create a shareable executive link." /></div>
      ) : (
        <>
          <div className="hero-panel">
            <div>
              <div className="hero-kicker">{periodLabel(latest)}</div>
              <h1>{latest.title}</h1>
              <p>{latest.executive_summary}</p>
            </div>
            <div className="hero-note">
              <div className="mini-title">Share link</div>
              <Link href={`/reports/${latest.share_token}`} className="mono">{shareUrl}</Link>
            </div>
          </div>
          <ReportSnapshot report={latest} />
          {reports.length > 1 ? (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="card-head"><h3>Previous reports</h3></div>
              <table className="tbl">
                <thead><tr><th>Period</th><th>Status</th><th className="r">Net saved</th><th className="r">Trust</th></tr></thead>
                <tbody>
                  {reports.slice(1).map((report) => (
                    <tr key={report.id}>
                      <td>{periodLabel(report)}</td>
                      <td><span className="pill neutral">{titleize(report.status)}</span></td>
                      <td className="r">{usd(report.net_savings_usd, 0)}</td>
                      <td className="r">{percent(report.trust_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

export function PublicReportView({ shareToken }: { shareToken: string }) {
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.publicReport(shareToken));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [shareToken]);
  useDeferredLoad(load);
  return (
    <div className="view">
      {loading || error || !report ? (
        <div className="card"><PageState loading={loading} error={error} empty={!report && !loading ? "Report not found" : undefined} /></div>
      ) : (
        <>
          <div className="hero-panel">
            <div>
              <div className="hero-kicker">{periodLabel(report)} · Executive view</div>
              <h1>{report.title}</h1>
              <p>{report.executive_summary}</p>
            </div>
            <div className="hero-note">This is a published Varsten report snapshot. It shows the numbers as generated for this period.</div>
          </div>
          <ReportSnapshot report={report} />
        </>
      )}
    </div>
  );
}
