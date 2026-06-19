"use client";

// Fills a panel body while its data/chart chunk loads. Sized to the cell so the
// swap to real content causes no layout shift.
export function PanelSkeleton() {
  return <div className="cc-skeleton" aria-hidden="true" />;
}

export function PanelEmpty({ label }: { label: string }) {
  return <div className="cc-panel-empty">{label}</div>;
}
