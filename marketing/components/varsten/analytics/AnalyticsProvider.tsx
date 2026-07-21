"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import {
  type AnalyticsEventName,
  type AnalyticsProperties,
  safeAnalyticsProperties,
} from "@/lib/analytics/events";

const anonymousIdKey = "varsten_marketing_anon_id";
const utmKeys = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];
const pageCategoryRules = [
  { prefix: "/docs", category: "docs" },
  { prefix: "/pricing", category: "pricing" },
  { prefix: "/proof", category: "proof" },
  { prefix: "/early-access", category: "early_access" },
  { prefix: "/enterprise", category: "enterprise" },
  { prefix: "/security", category: "security" },
  { prefix: "/contact", category: "contact" },
];

function uuidFallback() {
  return `anon_${Math.random().toString(36).slice(2)}_${Date.now().toString(36)}`;
}

function createAnonymousId() {
  return window.crypto?.randomUUID?.() ?? uuidFallback();
}

export function getMarketingAnonymousId() {
  if (typeof window === "undefined") return "server";

  const existing = window.localStorage.getItem(anonymousIdKey);
  if (existing) return existing;

  const nextId = createAnonymousId();
  window.localStorage.setItem(anonymousIdKey, nextId);
  return nextId;
}

function currentUtmParams(params: URLSearchParams): AnalyticsProperties {
  return Object.fromEntries(utmKeys.flatMap((key) => {
    const value = params.get(key);
    return value ? [[key, value]] : [];
  }));
}

function currentAttribution() {
  if (typeof window === "undefined") return {};

  const params = new URLSearchParams(window.location.search);
  return {
    path: window.location.pathname,
    search_present: window.location.search.length > 0,
    referrer: document.referrer || null,
    ...currentUtmParams(params),
  };
}

function pageCategory(pathname: string) {
  if (pathname === "/") return "home";
  return pageCategoryRules.find((rule) => pathname.startsWith(rule.prefix))?.category ?? "marketing";
}

function analyticsDebugEnabled() {
  return (
    process.env.NEXT_PUBLIC_ANALYTICS_DEBUG === "true" ||
    new URLSearchParams(window.location.search).get("analytics_debug") === "1"
  );
}

function sendAnalyticsPayload(payload: string) {
  const sent = navigator.sendBeacon?.("/api/analytics", new Blob([payload], { type: "application/json" }));
  if (sent) return;

  void fetch("/api/analytics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload,
    keepalive: true,
  });
}

export function trackMarketingEvent(event: AnalyticsEventName, properties: AnalyticsProperties = {}) {
  if (typeof window === "undefined") return;

  const body = {
    event,
    distinctId: getMarketingAnonymousId(),
    properties: safeAnalyticsProperties({
      ...currentAttribution(),
      page_category: pageCategory(window.location.pathname),
      ...properties,
    }),
  };

  if (analyticsDebugEnabled()) console.log("[analytics]", body);

  sendAnalyticsPayload(JSON.stringify(body));
}

export function AnalyticsProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    const event = pathname.startsWith("/docs") ? "docs page viewed" : "marketing page viewed";
    trackMarketingEvent(event, {
      path: pathname,
      page_category: pageCategory(pathname),
    });
  }, [pathname]);

  return children;
}
