"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import {
  type AnalyticsEventName,
  type AnalyticsProperties,
  safeAnalyticsProperties,
} from "@/lib/analytics/events";

const anonymousIdKey = "varsten_marketing_anon_id";

function uuidFallback() {
  return `anon_${Math.random().toString(36).slice(2)}_${Date.now().toString(36)}`;
}

export function getMarketingAnonymousId() {
  if (typeof window === "undefined") return "server";

  const existing = window.localStorage.getItem(anonymousIdKey);
  if (existing) return existing;

  const nextId = window.crypto?.randomUUID?.() ?? uuidFallback();
  window.localStorage.setItem(anonymousIdKey, nextId);
  return nextId;
}

function currentAttribution() {
  if (typeof window === "undefined") return {};

  const params = new URLSearchParams(window.location.search);
  const attribution: AnalyticsProperties = {
    path: window.location.pathname,
    search_present: window.location.search.length > 0,
    referrer: document.referrer || null,
  };

  for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"]) {
    const value = params.get(key);
    if (value) attribution[key] = value;
  }

  return attribution;
}

function pageCategory(pathname: string) {
  if (pathname === "/") return "home";
  if (pathname.startsWith("/docs")) return "docs";
  if (pathname.startsWith("/pricing")) return "pricing";
  if (pathname.startsWith("/proof")) return "proof";
  if (pathname.startsWith("/enterprise")) return "enterprise";
  if (pathname.startsWith("/security")) return "security";
  if (pathname.startsWith("/contact")) return "contact";
  return "marketing";
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

  const debug =
    process.env.NEXT_PUBLIC_ANALYTICS_DEBUG === "true" ||
    new URLSearchParams(window.location.search).get("analytics_debug") === "1";

  if (debug) console.log("[analytics]", body);

  const payload = JSON.stringify(body);
  if (navigator.sendBeacon) {
    const sent = navigator.sendBeacon("/api/analytics", new Blob([payload], { type: "application/json" }));
    if (sent) return;
  }

  void fetch("/api/analytics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload,
    keepalive: true,
  });
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
