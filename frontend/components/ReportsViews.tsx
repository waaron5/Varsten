"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { AttributionTable } from "@/components/AttributionTable";
import { RequireSession } from "@/components/RequireSession";
import { useProjectResource } from "@/components/useProjectResource";
import {
  numberValue,
  PageState,
  percent,
  titleize,
  useDeferredLoad,
} from "@/components/viewPrimitives";
import { api } from "@/lib/api";
import { compact, usd } from "@/lib/format";
import type { MonthlyReport } from "@/lib/types";

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
          <AttributionTable
            empty="No attributed savings yet"
            emptyDetail="Apply engine actions to build lever-level proof."
            rows={report.attribution_rows}
          />
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

function ReportHero({ report, shareUrl }: { report: MonthlyReport; shareUrl: string }) {
  return (
    <div className="hero-panel">
      <div>
        <div className="hero-kicker">{periodLabel(report)}</div>
        <h1>{report.title}</h1>
        <p>{report.executive_summary}</p>
      </div>
      <div className="hero-note">
        <div className="mini-title">Share link</div>
        <Link href={`/reports/${report.share_token}`} className="mono">{shareUrl}</Link>
      </div>
    </div>
  );
}

function PreviousReports({ reports }: { reports: MonthlyReport[] }) {
  if (reports.length <= 1) return null;
  return (
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
  );
}

function ReportsContent({
  latest,
  reports,
  shareUrl,
}: {
  latest: MonthlyReport;
  reports: MonthlyReport[];
  shareUrl: string;
}) {
  return (
    <>
      <ReportHero report={latest} shareUrl={shareUrl} />
      <ReportSnapshot report={latest} />
      <PreviousReports reports={reports} />
    </>
  );
}

function ReportsBody() {
  const {
    activeProjectId,
    data: reports,
    error,
    getToken,
    loading,
    setData: setReports,
    setError,
  } = useProjectResource<MonthlyReport[]>(api.reports, []);
  const [busy, setBusy] = useState(false);
  const latest = reports?.[0] ?? null;
  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await api.createReport(await getToken(), activeProjectId ?? undefined);
      setReports((current) => [report, ...(current ?? []).filter((item) => item.id !== report.id)]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const shareUrl = useMemo(() => (latest ? shareHref(latest) : ""), [latest]);
  return (
    <div className="view">
      <div className="page-head page-head-actions">
        <div className="spacer" />
        <button className="btn primary" disabled={busy} onClick={generate} type="button">{busy ? "Generating..." : "Generate current month"}</button>
      </div>

      {loading || error ? (
        <div className="card"><PageState loading={loading} error={error} /></div>
      ) : !latest ? (
        <div className="card"><PageState empty="No reports yet" emptyDetail="Generate the current month report to create a shareable executive link." /></div>
      ) : (
        <ReportsContent latest={latest} reports={reports ?? []} shareUrl={shareUrl} />
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
