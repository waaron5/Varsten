import { NextResponse } from "next/server";
import { captureServerEvent } from "@/lib/analytics/server";
import { isAnalyticsEventName, safeAnalyticsProperties } from "@/lib/analytics/events";

export const dynamic = "force-dynamic";

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export async function POST(request: Request) {
  let body: Record<string, unknown>;

  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const event = stringValue(body.event);
  const distinctId = stringValue(body.distinctId);

  if (!isAnalyticsEventName(event)) {
    return NextResponse.json({ error: "unknown analytics event" }, { status: 400 });
  }

  if (!distinctId) {
    return NextResponse.json({ error: "missing distinct id" }, { status: 400 });
  }

  try {
    await captureServerEvent({
      event,
      distinctId,
      properties: safeAnalyticsProperties(body.properties),
    });
  } catch (error) {
    console.error("analytics capture failed:", error);
    return NextResponse.json({ ok: false }, { status: 202 });
  }

  return NextResponse.json({ ok: true });
}
