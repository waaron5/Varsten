"use client";

import type { ReactNode } from "react";

// A grid-cell panel: fixed head + flexible body that charts/tables fill and clip.
export function Panel({
  title,
  sub,
  place,
  right,
  children,
}: {
  title: string;
  sub?: string;
  place?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={`card cc-panel${place ? ` ${place}` : ""}`}>
      <div className="cc-panel-head">
        <div className="cc-panel-titles">
          <h3>{title}</h3>
          {sub ? <span className="cc-panel-sub">{sub}</span> : null}
        </div>
        {right ? <div className="cc-panel-right">{right}</div> : null}
      </div>
      <div className="cc-panel-body">{children}</div>
    </section>
  );
}

export function KpiTile({
  label,
  value,
  sub,
  tone,
  spark,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "pos" | "neg";
  spark?: ReactNode;
}) {
  return (
    <div className="cc-kpi">
      <div className="cc-kpi-label">{label}</div>
      <div className={`cc-kpi-value${tone ? ` ${tone}` : ""}`}>{value}</div>
      {sub ? <div className="cc-kpi-sub">{sub}</div> : null}
      {spark ? <div className="cc-kpi-spark">{spark}</div> : null}
    </div>
  );
}

// Fills a panel body while its data/chart chunk loads. Sized to the cell so the
// swap to real content causes no layout shift.
export function PanelSkeleton() {
  return <div className="cc-skeleton" aria-hidden="true" />;
}

export function PanelEmpty({ label }: { label: string }) {
  return <div className="cc-panel-empty">{label}</div>;
}
