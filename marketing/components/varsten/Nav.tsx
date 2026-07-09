"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState } from "react";
import { APP_URL, START_TRIAL_HREF } from "@/app/site-links";

const RESOURCES_CLOSE_DELAY_MS = 250;

const PRODUCT_LINKS = [
  ["Levers", "#levers"],
  ["Integrations", "#integrations"],
  ["Pricing", "#pricing"],
] as const;

const RESOURCE_GROUPS = [
  {
    title: "Build",
    links: [
      ["Docs", "/docs", "Setup guide and integration notes"],
      ["Quickstart", "/docs#quickstart", "Point existing AI traffic at Varsten"],
      ["SDK reference", "/docs#sdk-reference", "Headers, attribution, and examples"],
      ["Architecture", "/docs#architecture", "How metering and optimization run inline"],
    ],
  },
  {
    title: "Evaluate",
    links: [
      ["Security", "/security", "Fail-open design and data handling"],
      ["FAQ", "/#faq", "Answers for engineering, finance, and procurement"],
      ["Status", "/status", "Service availability and health"],
      ["Changelog", "/changelog", "Recent product updates"],
    ],
  },
  {
    title: "Company",
    links: [
      ["About", "/about", "Who Varsten is for and why it exists"],
      ["Contact", "/contact", "Sales, support, security review, and pilots"],
      ["Privacy", "/privacy", "How account and operational data are handled"],
      ["Terms", "/terms", "Commercial and service terms"],
    ],
  },
] as const;

export function Nav() {
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const closeTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openResources = () => {
    if (closeTimeout.current) clearTimeout(closeTimeout.current);
    setResourcesOpen(true);
  };
  const closeResourcesSoon = () => {
    if (closeTimeout.current) clearTimeout(closeTimeout.current);
    closeTimeout.current = setTimeout(() => setResourcesOpen(false), RESOURCES_CLOSE_DELAY_MS);
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-6 md:px-10">
        <div className="flex min-w-0 items-center gap-8">
          <a
            href="#top"
            className="group/logo flex shrink-0 items-center"
            aria-label="Varsten home"
          >
            <span className="relative block h-4 aspect-[445/88]">
              <Image
                src="/varsten-logo.svg"
                alt=""
                aria-hidden="true"
                fill
                className="object-contain transition-opacity duration-150 group-hover/logo:opacity-0"
                priority
              />
              <Image
                src="/varsten-logo-blue.svg"
                alt=""
                aria-hidden="true"
                fill
                className="object-contain opacity-0 transition-opacity duration-150 group-hover/logo:opacity-100"
              />
            </span>
          </a>
          <nav className="hidden items-center gap-7 md:flex" aria-label="Primary">
            <div
              className="group/resources"
              onMouseEnter={openResources}
              onMouseLeave={closeResourcesSoon}
            >
              <button
                aria-expanded={resourcesOpen}
                aria-haspopup="true"
                className="inline-flex h-9 items-center gap-1.5 text-[13px] text-ink-soft transition-colors hover:text-ink"
                onFocus={openResources}
                onBlur={closeResourcesSoon}
                type="button"
              >
                Resources
                <svg
                  aria-hidden="true"
                  className={`h-3.5 w-3.5 translate-y-px transition-transform group-hover/resources:rotate-180 group-focus-within/resources:rotate-180 ${
                    resourcesOpen ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.8"
                  viewBox="0 0 24 24"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </button>
              <div
                className={`absolute inset-x-0 top-full z-50 -mt-px opacity-0 transition duration-150 group-hover/resources:visible group-hover/resources:opacity-100 group-focus-within/resources:visible group-focus-within/resources:opacity-100 ${
                  resourcesOpen ? "visible opacity-100" : "invisible"
                }`}
                onMouseEnter={openResources}
                onMouseLeave={closeResourcesSoon}
              >
                <div className="mx-auto max-w-[1400px] px-6 md:px-10">
                  <div className="border border-border bg-background shadow-[0_16px_50px_rgba(17,17,17,0.10)]">
                    <div className="grid md:grid-cols-3">
                      {RESOURCE_GROUPS.map((group) => (
                        <section
                          key={group.title}
                          className="border-t border-border p-4 first:border-t-0 md:border-l md:border-t-0 md:first:border-l-0"
                        >
                          <div className="mono mb-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                            {group.title}
                          </div>
                          <div className="grid gap-1">
                            {group.links.map(([label, href, detail]) => (
                              <a
                                key={label}
                                href={href}
                                className="block border-l-2 border-transparent px-3 py-2.5 transition-colors hover:border-blueprint hover:bg-secondary"
                              >
                                <span className="block text-[13px] font-medium text-ink">
                                  {label}
                                </span>
                                <span className="mt-0.5 block text-[12px] leading-5 text-ink-soft">
                                  {detail}
                                </span>
                              </a>
                            ))}
                          </div>
                        </section>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            {PRODUCT_LINKS.map(([label, href]) => (
              <a
                key={label}
                href={href}
                className="text-[13px] text-ink-soft transition-colors hover:text-ink"
              >
                {label}
              </a>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <a
            href={APP_URL}
            className="hidden text-[13px] text-ink-soft transition-colors hover:text-ink md:inline"
          >
            Sign in
          </a>
          <Link
            href={START_TRIAL_HREF}
            className="inline-flex h-8 items-center gap-2 bg-ink px-3 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Start free trial
            <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
