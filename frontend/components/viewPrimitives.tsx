"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { useEffect } from "react";

import { LEVER_LABELS as SAVINGS_LEVER_LABELS } from "@/lib/levers";

export type TabLink = {
  href: string;
  label: string;
};

const LEVER_LABELS: Record<string, string> = {
  ...SAVINGS_LEVER_LABELS,
  prompt_cache: "Prompt cache",
};

export function titleize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

export function leverLabel(value: string | null | undefined): string {
  if (!value) return "General";
  return LEVER_LABELS[value] ?? titleize(value);
}

export function numberValue(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function percent(value: string | number | null | undefined, scale = 100): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${Math.round(n * scale)}%`;
}

export function plainPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n}%`;
}

export function signedPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

export function riskClass(risk: string): string {
  const normalized = risk.toLowerCase();
  if (normalized.includes("high")) return "amber";
  if (normalized.includes("medium")) return "accent";
  return "green";
}

export function useDeferredLoad(load: () => Promise<void>) {
  useEffect(() => {
    void load();
  }, [load]);
}

export function PageHeader({
  action,
}: {
  section: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  if (!action) return null;
  return (
    <div className="page-head">
      <div className="spacer" />
      {action}
    </div>
  );
}

export function Tabs({ tabs, active }: { tabs: TabLink[]; active: string }) {
  return (
    <div className="tabs">
      {tabs.map((tab) => (
        <Link key={tab.href} href={tab.href} className={`tab ${active === tab.href ? "active" : ""}`}>
          {tab.label}
        </Link>
      ))}
    </div>
  );
}

export function NoticeCard({
  badge,
  children,
  style,
  title,
}: {
  badge: string;
  children: ReactNode;
  style?: CSSProperties;
  title: string;
}) {
  return (
    <div className="card" style={style}>
      <div className="card-head">
        <h3>{title}</h3>
        <div className="right"><span className="pill neutral">{badge}</span></div>
      </div>
      <div className="es" style={{ padding: "0 12px 12px" }}>
        {children}
      </div>
    </div>
  );
}

export function PageState({
  loading,
  error,
  empty,
  emptyDetail,
  errorTitle = "Could not load this view",
}: {
  loading?: boolean;
  error?: string | null;
  empty?: string;
  emptyDetail?: string;
  errorTitle?: string;
}) {
  if (loading) return <div className="empty"><div className="spinner" /></div>;
  if (error) {
    return (
      <div className="empty">
        <div className="et">{errorTitle}</div>
        <div className="es">{error}</div>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="empty">
        <div className="et">{empty}</div>
        {emptyDetail ? <div className="es">{emptyDetail}</div> : null}
      </div>
    );
  }
  return null;
}

export function CollectionState<T>({
  children,
  empty,
  emptyDetail,
  error,
  items,
  loading,
}: {
  children: (items: readonly T[]) => ReactNode;
  empty: string;
  emptyDetail?: string;
  error?: string | null;
  items: readonly T[] | null | undefined;
  loading?: boolean;
}) {
  if (loading || error) return <PageState loading={loading} error={error} />;
  if (!items || items.length === 0) return <PageState empty={empty} emptyDetail={emptyDetail} />;
  return <>{children(items)}</>;
}

export function QualityBar({ label, value }: { label: string; value: string | number | null | undefined }) {
  const width = Math.max(0, Math.min(100, numberValue(value) * 100));
  return (
    <div className="quality-row">
      <div className="quality-label">
        <span>{label}</span>
        <b>{percent(value)}</b>
      </div>
      <div className="quality-track"><i style={{ width: `${width}%` }} /></div>
    </div>
  );
}

export function BinaryPill({
  active,
  activeLabel,
  inactiveLabel,
  activeTone = "green",
  inactiveTone = "neutral",
}: {
  active: boolean;
  activeLabel: string;
  inactiveLabel: string;
  activeTone?: string;
  inactiveTone?: string;
}) {
  return (
    <span className={`pill ${active ? activeTone : inactiveTone}`}>
      {active ? activeLabel : inactiveLabel}
    </span>
  );
}
