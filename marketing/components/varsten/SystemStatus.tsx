"use client";

import { useEffect, useState } from "react";

type ServiceStatus = "operational" | "degraded" | "outage" | "maintenance" | "unknown";

type StatusPayload = {
  status?: ServiceStatus;
  label?: string;
  status_page_url?: string;
};

const labels: Record<ServiceStatus, string> = {
  operational: "All systems nominal",
  degraded: "Service degraded",
  outage: "Service outage",
  maintenance: "Maintenance in progress",
  unknown: "Status unavailable",
};

const dotClass: Record<ServiceStatus, string> = {
  operational: "bg-blueprint",
  degraded: "bg-amber-500",
  outage: "bg-red-600",
  maintenance: "bg-amber-500",
  unknown: "bg-ink-soft",
};

function statusFromPayload(payload: StatusPayload | null): ServiceStatus {
  if (!payload?.status) return "unknown";
  if (payload.status in labels) return payload.status;
  return "unknown";
}

async function fetchStatusPayload(signal: AbortSignal): Promise<StatusPayload> {
  const response = await fetch("/api/status", {
    cache: "no-store",
    signal,
  });
  if (!response.ok) return { status: "unknown" };
  return (await response.json()) as StatusPayload;
}

function useSystemStatusPayload() {
  const [payload, setPayload] = useState<StatusPayload | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadStatus() {
      try {
        setPayload(await fetchStatusPayload(controller.signal));
      } catch {
        if (!controller.signal.aborted) {
          setPayload({ status: "unknown" });
        }
      }
    }

    loadStatus();
    const interval = window.setInterval(loadStatus, 60_000);

    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, []);

  return payload;
}

function statusLabel(payload: StatusPayload | null, status: ServiceStatus): string {
  return payload?.label ?? labels[status];
}

function statusHref(payload: StatusPayload | null): string {
  return payload?.status_page_url ?? "/status";
}

function statusDisplay(payload: StatusPayload | null) {
  const status = statusFromPayload(payload);
  return {
    status,
    label: statusLabel(payload, status),
    href: statusHref(payload),
  };
}

export function SystemStatus() {
  const { href, label, status } = statusDisplay(useSystemStatusPayload());
  return (
    <a
      href={href}
      className="flex items-center gap-2 transition-colors hover:text-ink"
      aria-label={`System status: ${label}`}
    >
      <span className={`inline-block h-1.5 w-1.5 ${dotClass[status]}`} />
      <span>{label}</span>
    </a>
  );
}
