import { NextResponse } from "next/server";
import { captureServerEvent } from "@/lib/analytics/server";
import { isAnalyticsEventName, safeAnalyticsProperties } from "@/lib/analytics/events";

export const dynamic = "force-dynamic";

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

async function analyticsRequestBody(request: Request): Promise<Record<string, unknown> | NextResponse> {
  try {
    return (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
}

function validatedAnalyticsEvent(body: Record<string, unknown>) {
  const event = stringValue(body.event);
  const distinctId = stringValue(body.distinctId);

  if (!isAnalyticsEventName(event)) {
    return NextResponse.json({ error: "unknown analytics event" }, { status: 400 });
  }

  if (!distinctId) {
    return NextResponse.json({ error: "missing distinct id" }, { status: 400 });
  }

  return { event, distinctId, properties: safeAnalyticsProperties(body.properties) };
}

async function captureAnalyticsEvent({
  distinctId,
  event,
  properties,
}: {
  distinctId: string;
  event: Parameters<typeof captureServerEvent>[0]["event"];
  properties: ReturnType<typeof safeAnalyticsProperties>;
}) {
  try {
    await captureServerEvent({ event, distinctId, properties });
  } catch (error) {
    console.error("analytics capture failed:", error);
    return NextResponse.json({ ok: false }, { status: 202 });
  }

  return NextResponse.json({ ok: true });
}

export async function POST(request: Request) {
  const body = await analyticsRequestBody(request);
  if (body instanceof NextResponse) return body;

  const analyticsEvent = validatedAnalyticsEvent(body);
  if (analyticsEvent instanceof NextResponse) return analyticsEvent;

  return captureAnalyticsEvent(analyticsEvent);
}
