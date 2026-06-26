import { NextResponse } from "next/server";

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
  const fullName =
    typeof (body as { fullName?: unknown })?.fullName === "string"
      ? (body as { fullName: string }).fullName.trim()
      : "";
  if (fullName.length < 2) {
    return NextResponse.json({ error: "invalid full name" }, { status: 400 });
  }
  const companyName =
    typeof (body as { companyName?: unknown })?.companyName === "string"
      ? (body as { companyName: string }).companyName.trim()
      : "";
  if (companyName.length < 2) {
    return NextResponse.json({ error: "invalid company name" }, { status: 400 });
  }

  const lead: LeadPayload = {
    email,
    fullName,
    companyName,
    source: typeof (body as { source?: unknown })?.source === "string" ? (body as { source: string }).source : "landing",
    submittedAt: new Date().toISOString(),
  };

  const webhookUrl = process.env.LEAD_WEBHOOK_URL;
  const resendKey = process.env.RESEND_API_KEY;
  const notifyEmail = process.env.LEADS_NOTIFY_EMAIL;
  const fromEmail = process.env.LEADS_FROM_EMAIL;
  const calendlyUrl = process.env.LEADS_CALENDLY_URL;

  try {
    if (webhookUrl) {
      await deliverToWebhook(webhookUrl, lead);
    } else if (resendKey && notifyEmail && fromEmail && calendlyUrl) {
      await deliverViaResend(resendKey, notifyEmail, fromEmail, calendlyUrl, lead);
    } else if (process.env.NODE_ENV === "production") {
      console.error(
        "lead capture misconfigured: no LEAD_WEBHOOK_URL or complete RESEND_API_KEY/LEADS_NOTIFY_EMAIL/LEADS_FROM_EMAIL/LEADS_CALENDLY_URL set",
      );
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
