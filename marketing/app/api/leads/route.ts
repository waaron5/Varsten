import { NextResponse } from "next/server";

// Lead capture for the landing page CTAs. The destination is configured by
// environment, in priority order:
//   1. LEAD_WEBHOOK_URL  — any JSON webhook (Zapier, Make, Slack, Formspree...)
//   2. RESEND_API_KEY + LEADS_NOTIFY_EMAIL — emails the lead to the founder
// In production a missing destination is a hard 503 so misconfiguration fails
// loudly instead of silently discarding leads. In dev it logs and succeeds.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type LeadPayload = {
  email: string;
  source: string;
  submittedAt: string;
};

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

async function deliverViaResend(apiKey: string, notifyEmail: string, lead: LeadPayload): Promise<void> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: process.env.LEADS_FROM_EMAIL ?? "Varsten Leads <onboarding@resend.dev>",
      to: [notifyEmail],
      subject: `New Varsten lead: ${lead.email}`,
      text: `Email: ${lead.email}\nSource: ${lead.source}\nSubmitted: ${lead.submittedAt}`,
    }),
  });
  if (!res.ok) {
    throw new Error(`resend responded ${res.status}`);
  }
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const email = typeof (body as { email?: unknown })?.email === "string" ? (body as { email: string }).email.trim() : "";
  if (!EMAIL_RE.test(email)) {
    return NextResponse.json({ error: "invalid email" }, { status: 400 });
  }

  const lead: LeadPayload = {
    email,
    source: typeof (body as { source?: unknown })?.source === "string" ? (body as { source: string }).source : "landing",
    submittedAt: new Date().toISOString(),
  };

  const webhookUrl = process.env.LEAD_WEBHOOK_URL;
  const resendKey = process.env.RESEND_API_KEY;
  const notifyEmail = process.env.LEADS_NOTIFY_EMAIL;

  try {
    if (webhookUrl) {
      await deliverToWebhook(webhookUrl, lead);
    } else if (resendKey && notifyEmail) {
      await deliverViaResend(resendKey, notifyEmail, lead);
    } else if (process.env.NODE_ENV === "production") {
      console.error("lead capture misconfigured: no LEAD_WEBHOOK_URL or RESEND_API_KEY/LEADS_NOTIFY_EMAIL set");
      return NextResponse.json({ error: "lead capture is not configured" }, { status: 503 });
    } else {
      console.log("[dev] lead captured (no destination configured):", lead);
    }
  } catch (err) {
    console.error("lead delivery failed:", err);
    return NextResponse.json({ error: "lead delivery failed" }, { status: 502 });
  }

  return NextResponse.json({ ok: true });
}
