"use client";

// The dashboard's period toggle + Export, rendered in the top navbar to match the
// mockup. Reads the shared period from DashboardChrome (the dashboard page reads
// the same value to drive its snapshot query) and owns the CSV download.

import { useId, useState } from "react";
import { useSession } from "@/components/session";
import { useDashboardChrome, periodSubtitle } from "@/components/dashboardChrome";
import { api } from "@/lib/api";
import type { DashboardPeriod } from "@/lib/types";

const PERIODS: DashboardPeriod[] = ["month", "quarter", "year"];

export function DashboardCrumb() {
  const { period } = useDashboardChrome();
  return <span>{periodSubtitle(period)}</span>;
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M5 20h14" />
    </svg>
  );
}

export function DashboardTopbarControls() {
  const { period, setPeriod } = useDashboardChrome();
  const { getToken, activeProjectId, status } = useSession();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportErrorId = useId();
  const exportDisabled = exporting || status !== "ready" || !activeProjectId;

  async function handleExport() {
    if (exportDisabled) return;
    setExporting(true);
    setExportError(null);
    try {
      const csv = await api.dashboardExportCsv(await getToken(), activeProjectId, { period });
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `varsten-dashboard-${period}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Could not export dashboard CSV.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="lv-topbar-actions">
      <div className="lv-period-tabs" role="tablist" aria-label="Reporting period">
        {PERIODS.map((p) => (
          <button
            key={p}
            role="tab"
            aria-selected={period === p}
            className={period === p ? "active" : ""}
            onClick={() => {
              setExportError(null);
              setPeriod(p);
            }}
          >
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>
      <button
        className="lv-export"
        onClick={handleExport}
        disabled={exportDisabled}
        aria-describedby={exportError ? exportErrorId : undefined}
      >
        <DownloadIcon />
        {exporting ? "Exporting..." : "Export CSV"}
      </button>
      {exportError ? (
        <span className="lv-export-error" id={exportErrorId} role="status">
          {exportError}
        </span>
      ) : null}
    </div>
  );
}
