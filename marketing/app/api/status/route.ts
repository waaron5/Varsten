import { NextResponse } from "next/server";

type ServiceStatus = "operational" | "degraded" | "outage" | "maintenance" | "unknown";

type StatusResponse = {
  status: ServiceStatus;
  label: string;
  checked_at: string;
  configured: boolean;
  status_page_url: string;
};

const endpointUrl = process.env.STATUS_ENDPOINT_URL || process.env.NEXT_PUBLIC_STATUS_ENDPOINT_URL;
const statusPageUrl = process.env.STATUS_PAGE_URL || process.env.NEXT_PUBLIC_STATUS_PAGE_URL || "/status";
const timeoutMs = 2_500;

export const dynamic = "force-dynamic";

const directStatusAliases: Record<string, ServiceStatus> = {
  healthy: "operational",
  nominal: "operational",
  none: "operational",
  ok: "operational",
  operational: "operational",
  up: "operational",
};

const partialStatusMatches: { status: ServiceStatus; tokens: string[] }[] = [
  { status: "maintenance", tokens: ["maintenance"] },
  { status: "degraded", tokens: ["degraded", "partial"] },
  { status: "outage", tokens: ["outage", "down", "critical"] },
];

const statusLabels: Record<ServiceStatus, string> = {
  operational: "All systems nominal",
  degraded: "Service degraded",
  outage: "Service outage",
  maintenance: "Maintenance in progress",
  unknown: "Status unavailable",
};

const severityOrder: ServiceStatus[] = ["outage", "degraded", "maintenance", "operational"];

function normalizeStatus(value: unknown): ServiceStatus | null {
  return typeof value === "string" ? statusFromText(value) : null;
}

function statusFromText(value: string): ServiceStatus | null {
  const normalized = value.toLowerCase().replace(/[\s-]+/g, "_");
  const alias = directStatusAliases[normalized];
  if (alias) return alias;
  return partialStatusMatches.find(({ tokens }) => tokens.some((token) => normalized.includes(token)))?.status ?? null;
}

function labelForStatus(status: ServiceStatus): string {
  return statusLabels[status];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function mostSevere(statuses: ServiceStatus[]): ServiceStatus | null {
  return severityOrder.find((status) => statuses.includes(status)) ?? null;
}

function firstStatus(...values: unknown[]): ServiceStatus | null {
  for (const value of values) {
    const status = normalizeStatus(value);
    if (status) return status;
  }
  return null;
}

function statusFromNestedStatus(body: Record<string, unknown>): ServiceStatus | null {
  if (!isRecord(body.status)) return null;
  return firstStatus(body.status.indicator, body.status.description, body.status.status);
}

function statusFromComponents(body: Record<string, unknown>): ServiceStatus | null {
  if (!Array.isArray(body.components)) return null;
  const componentStatuses = body.components
    .map((component) => (isRecord(component) ? normalizeStatus(component.status) : null))
    .filter((status): status is ServiceStatus => Boolean(status));
  return mostSevere(componentStatuses);
}

function statusFromDataAttributes(body: Record<string, unknown>): ServiceStatus | null {
  if (!isRecord(body.data) || !isRecord(body.data.attributes)) return null;
  return firstStatus(body.data.attributes.status, body.data.attributes.indicator, body.data.attributes.state);
}

const statusBodyReaders = [
  statusFromNestedStatus,
  statusFromComponents,
  statusFromDataAttributes,
  (body: Record<string, unknown>) =>
    firstStatus(body.status, body.indicator, body.state, body.overall_status, body.description),
];

function statusFromBody(body: unknown): ServiceStatus | null {
  if (!isRecord(body)) return null;
  return statusBodyReaders.map((readStatus) => readStatus(body)).find(Boolean) ?? null;
}

async function jsonBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return null;
  return response.json();
}

async function upstreamStatus(url: string): Promise<ServiceStatus> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: controller.signal,
      headers: { accept: "application/json" },
    });

    return statusFromBody(await jsonBody(response)) ?? (response.ok ? "operational" : "outage");
  } catch {
    return "unknown";
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET() {
  const status = endpointUrl ? await upstreamStatus(endpointUrl) : "unknown";
  const body: StatusResponse = {
    status,
    label: labelForStatus(status),
    checked_at: new Date().toISOString(),
    configured: Boolean(endpointUrl),
    status_page_url: statusPageUrl,
  };

  return NextResponse.json(body, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
    },
  });
}
