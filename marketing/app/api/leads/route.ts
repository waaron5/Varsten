import { NextResponse } from "next/server";
import { captureServerEvent } from "@/lib/analytics/server";

// Lead capture for the landing page CTAs. The destination is configured by
// environment, in priority order:
//   1. LEAD_WEBHOOK_URL  — any JSON webhook (Zapier, Make, Slack, Formspree...)
//   2. RESEND_API_KEY + LEADS_NOTIFY_EMAIL + LEADS_FROM_EMAIL + LEADS_CALENDLY_URL
//      emails the buyer and notifies the founder.
// In production a missing destination is a hard 503 so misconfiguration fails
// loudly instead of silently discarding leads. In dev it logs and succeeds.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type LeadPayload = {
  email: string;
  fullName: string;
  companyName: string;
  source: string;
  submittedAt: string;
  anonymousId: string;
  pagePath: string;
  utmSource: string;
  utmMedium: string;
  utmCampaign: string;
};

type LeadDeliveryConfig =
  | { kind: "webhook"; url: string }
  | { kind: "resend"; apiKey: string; notifyEmail: string; fromEmail: string; calendlyUrl: string }
  | { kind: "dev-log" }
  | { kind: "missing" };

class LeadValidationError extends Error {}

function readString(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  return typeof value === "string" ? value.trim() : "";
}

function invalidLeadResponse(message: string) {
  return NextResponse.json({ error: message }, { status: 400 });
}

function requiredLeadString(body: Record<string, unknown>, key: string, label: string): string {
  const value = readString(body, key);
  if (value.length >= 2) return value;
  throw new LeadValidationError(`invalid ${label}`);
}

function requiredEmail(body: Record<string, unknown>): string {
  const email = readString(body, "email");
  if (EMAIL_RE.test(email)) return email;
  throw new LeadValidationError("invalid email");
}

function safePath(path: string): string {
  return path.startsWith("/") && !path.startsWith("//") ? path.slice(0, 180) : "";
}

function safeAttribution(value: string): string {
  return value.replace(/[^\w .:/-]/g, "").slice(0, 180);
}

function anonymousIdFromBody(body: Record<string, unknown>): string {
  const anonymousId = readString(body, "anonymousId");
  return anonymousId || `lead-${crypto.randomUUID()}`;
}

function leadFromBody(body: Record<string, unknown>): LeadPayload | NextResponse {
  try {
    return {
      email: requiredEmail(body),
      fullName: requiredLeadString(body, "fullName", "full name"),
      companyName: requiredLeadString(body, "companyName", "company name"),
      source: readString(body, "source") || "landing",
      submittedAt: new Date().toISOString(),
      anonymousId: anonymousIdFromBody(body),
      pagePath: safePath(readString(body, "pagePath")),
      utmSource: safeAttribution(readString(body, "utmSource")),
      utmMedium: safeAttribution(readString(body, "utmMedium")),
      utmCampaign: safeAttribution(readString(body, "utmCampaign")),
    };
  } catch (error) {
    return invalidLeadResponse(error instanceof Error ? error.message : "invalid lead");
  }
}

function resendConfig(): LeadDeliveryConfig | null {
  const config = {
    apiKey: process.env.RESEND_API_KEY,
    notifyEmail: process.env.LEADS_NOTIFY_EMAIL,
    fromEmail: process.env.LEADS_FROM_EMAIL,
    calendlyUrl: process.env.LEADS_CALENDLY_URL,
  };
  return Object.values(config).every(Boolean) ? { kind: "resend", ...config } as LeadDeliveryConfig : null;
}

function deliveryConfig(): LeadDeliveryConfig {
  const webhookUrl = process.env.LEAD_WEBHOOK_URL;
  if (webhookUrl) return { kind: "webhook", url: webhookUrl };
  const resend = resendConfig();
  if (resend) return resend;
  return process.env.NODE_ENV === "production" ? { kind: "missing" } : { kind: "dev-log" };
}

async function deliverToWebhook(url: string, lead: LeadPayload): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(lead),
  });
  if (!res.ok) {
    throw new Error(`lead webhook responded ${res.status}`);
  }
}

async function sendResendEmail({
  apiKey,
  from,
  to,
  subject,
  text,
}: {
  apiKey: string;
  from: string;
  to: string;
  subject: string;
  text: string;
}): Promise<void> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [to],
      subject,
      text,
    }),
  });
  if (!res.ok) {
    throw new Error(`resend responded ${res.status}`);
  }
}

async function deliverViaResend(
  apiKey: string,
  notifyEmail: string,
  fromEmail: string,
  calendlyUrl: string,
  lead: LeadPayload,
): Promise<void> {
  const buyerFirstName = lead.fullName.split(/\s+/, 1)[0] || lead.fullName;
  await sendResendEmail({
    apiKey,
    from: fromEmail,
    to: lead.email,
    subject: "Varsten setup",
    text: `Hey ${buyerFirstName},

Thanks for checking out Varsten.

We do the first setup manually because this touches production AI traffic. I want to make sure your tenant, API keys, provider routing, and isolation are correct from minute one.

Grab a 15-minute setup slot here:
${calendlyUrl}

Calendly will ask for your framework and current request volume so I can come prepared.

-Aaron`,
  });

  await sendResendEmail({
    apiKey,
    from: fromEmail,
    to: notifyEmail,
    subject: `New Varsten setup request: ${lead.companyName}`,
    text: `New Varsten setup request

Name: ${lead.fullName}
Company: ${lead.companyName}
Email: ${lead.email}
Source: ${lead.source}
Submitted: ${lead.submittedAt}

Buyer autoresponder: sent`,
  });
}

async function deliverLead(lead: LeadPayload): Promise<NextResponse | null> {
  const config = deliveryConfig();
  if (config.kind === "webhook") {
    await deliverToWebhook(config.url, lead);
    return null;
  }
  if (config.kind === "resend") {
    await deliverViaResend(config.apiKey, config.notifyEmail, config.fromEmail, config.calendlyUrl, lead);
    return null;
  }
  if (config.kind === "dev-log") {
    console.log("[dev] lead captured (no destination configured):", lead);
    return null;
  }

  console.error(
    "lead capture misconfigured: no LEAD_WEBHOOK_URL or complete RESEND_API_KEY/LEADS_NOTIFY_EMAIL/LEADS_FROM_EMAIL/LEADS_CALENDLY_URL set",
  );
  return NextResponse.json({ error: "lead capture is not configured" }, { status: 503 });
}

export async function POST(request: Request) {
  const lead = await leadFromRequest(request);
  if (lead instanceof NextResponse) return lead;
  return leadResponse(lead);
}

async function leadResponse(lead: LeadPayload) {
  try {
    const failure = await deliverLead(lead);
    if (failure) return failure;
    await captureLeadSubmitted(lead);
  } catch (err) {
    console.error("lead delivery failed:", err);
    return NextResponse.json({ error: "lead delivery failed" }, { status: 502 });
  }

  return NextResponse.json({ ok: true });
}

async function captureLeadSubmitted(lead: LeadPayload) {
  try {
    await captureServerEvent({
      event: "lead form submitted",
      distinctId: lead.anonymousId,
      properties: {
        source: lead.source,
        path: lead.pagePath,
        utm_source: lead.utmSource || null,
        utm_medium: lead.utmMedium || null,
        utm_campaign: lead.utmCampaign || null,
      },
    });
  } catch (error) {
    console.error("lead analytics capture failed:", error);
  }
}

async function leadFromRequest(request: Request): Promise<LeadPayload | NextResponse> {
  const body = await requestBody(request);
  if (body instanceof NextResponse) return body;
  return leadFromBody(body);
}

async function requestBody(request: Request): Promise<Record<string, unknown> | NextResponse> {
  try {
    return (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
}
