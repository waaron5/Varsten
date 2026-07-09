"use client";

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { trackMarketingEvent } from "./analytics/AnalyticsProvider";
import type { AnalyticsEventName, AnalyticsProperties } from "@/lib/analytics/events";

type TrackedLinkProps = Omit<ComponentProps<typeof Link>, "onClick"> & {
  children: ReactNode;
  event?: AnalyticsEventName;
  eventProperties?: AnalyticsProperties;
  additionalEvents?: { event: AnalyticsEventName; properties?: AnalyticsProperties }[];
};

export function TrackedLink({
  children,
  event = "cta clicked",
  eventProperties,
  additionalEvents = [],
  href,
  ...props
}: TrackedLinkProps) {
  const destination = typeof href === "string" ? href : href.toString();

  return (
    <Link
      href={href}
      onClick={() => {
        const commonProperties = {
          destination,
          ...eventProperties,
        };

        trackMarketingEvent("cta clicked", commonProperties);
        if (event !== "cta clicked") trackMarketingEvent(event, commonProperties);
        for (const additionalEvent of additionalEvents) {
          trackMarketingEvent(additionalEvent.event, {
            ...commonProperties,
            ...additionalEvent.properties,
          });
        }
      }}
      {...props}
    >
      {children}
    </Link>
  );
}
