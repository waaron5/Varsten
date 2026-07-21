"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";
import { CONTACT_HREF, EARLY_ACCESS_HREF, SIGN_IN_HREF } from "@/app/site-links";
import { trackMarketingEvent } from "./analytics/AnalyticsProvider";

const NAV_DROPDOWN_CLOSE_DELAY_MS = 250;

const PRODUCT_LINKS = [
  ["Pricing", "/pricing"],
] as const;

const PAGE_LABELS_BY_SEGMENT: Record<string, string> = {
  about: "About",
  contact: "Contact",
  docs: "Docs",
  "early-access": "Early access",
  enterprise: "Enterprise",
  faq: "FAQ",
  pricing: "Pricing",
  "product-tour": "Product",
  privacy: "Privacy",
  proof: "Savings proof",
  security: "Security",
  terms: "Terms",
};

type NavDropdownLink = { label: string; href: string | null; detail: string; soon?: boolean };
type NavDropdownGroup = { title?: string; links: NavDropdownLink[] };

const RESOURCE_GROUPS: NavDropdownGroup[] = [
  {
    title: "Learn",
    links: [
      { label: "Product", href: "/product-tour", detail: "Explore the dashboard for spend, savings, and cost drivers" },
      { label: "Docs", href: "/docs/quickstart", detail: "Guides, API notes, and integration reference" },
      { label: "FAQ", href: "/faq", detail: "Answers for engineering, finance, and procurement" },
    ],
  },
  {
    title: "Evaluate",
    links: [
      { label: "Savings proof", href: "/proof", detail: "How verified savings are measured" },
      { label: "Security", href: "/security", detail: "Fail-open design and data handling" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", href: "/about", detail: "Who Varsten is for and why it exists" },
      { label: "Contact", href: CONTACT_HREF, detail: "Sales, support, security review, and pilots" },
      { label: "Privacy", href: "/privacy", detail: "How account and operational data are handled" },
      { label: "Terms", href: "/terms", detail: "Commercial and service terms" },
    ],
  },
];

const INTEGRATE_GROUPS: NavDropdownGroup[] = [
  { links: [{ label: "Metadata only", href: "/#integrations", detail: "Zero content egress — async usage events after your own provider call." }] },
  { links: [{ label: "Base URL change", href: "/#integrations", detail: "Point a stock OpenAI client at Varsten for the fastest proxy trial." }] },
  { links: [{ label: "SDK", href: "/#integrations", detail: "Optimized and fail-open — the wrapper for production traffic." }] },
  { links: [{ label: "Sidecar", href: null, detail: "In-VPC sidecar deployment, split from the control plane.", soon: true }] },
];

function pageLabelFromPathname(pathname: string) {
  const firstSegment = pathname.split("/").filter(Boolean)[0];
  return firstSegment ? PAGE_LABELS_BY_SEGMENT[firstSegment] ?? null : null;
}

function NavDropdown({
  columns,
  groups,
  label,
  open,
  onOpen,
  onCloseSoon,
}: {
  columns: 3 | 4;
  groups: NavDropdownGroup[];
  label: string;
  open: boolean;
  onOpen: () => void;
  onCloseSoon: () => void;
}) {
  return (
    <div onMouseEnter={onOpen} onMouseLeave={onCloseSoon}>
      <button
        aria-expanded={open}
        aria-haspopup="true"
        className="inline-flex h-9 items-center gap-1.5 text-[13px] text-ink-soft transition-colors hover:text-ink"
        onFocus={onOpen}
        onBlur={onCloseSoon}
        type="button"
      >
        {label}
        <svg
          aria-hidden="true"
          className={`h-3.5 w-3.5 translate-y-px transition-transform ${open ? "rotate-180" : ""}`}
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
        className={`absolute inset-x-0 top-full z-50 opacity-0 transition duration-150 ${
          open ? "visible opacity-100" : "invisible"
        }`}
        onMouseEnter={onOpen}
        onMouseLeave={onCloseSoon}
      >
        <div className="mx-auto max-w-[1400px] px-6 md:px-10">
          <div className="border border-border bg-background shadow-[0_16px_50px_rgba(17,17,17,0.10)]">
            <div className={`grid ${columns === 4 ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
              {groups.map((group, index) => (
                <section
                  key={group.title ?? index}
                  className="border-t border-border p-4 first:border-t-0 md:border-l md:border-t-0 md:first:border-l-0"
                >
                  {group.title ? (
                    <div className="mono mb-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                      {group.title}
                    </div>
                  ) : null}
                  <div className="grid">
                    {group.links.map((link) =>
                      link.href ? (
                        <a
                          key={link.label}
                          href={link.href}
                          className="block border-l-2 border-transparent px-3 py-2 transition-colors duration-75 ease-out hover:border-blueprint hover:bg-secondary"
                        >
                          <span className="block text-[13px] font-medium text-ink">
                            {link.label}
                          </span>
                          <span className="mt-0.5 block text-[12px] leading-5 text-ink-soft">
                            {link.detail}
                          </span>
                        </a>
                      ) : (
                        <div key={link.label} className="block border-l-2 border-transparent px-3 py-2 opacity-60">
                          <span className="flex items-center gap-2 text-[13px] font-medium text-ink">
                            {link.label}
                            {link.soon ? (
                              <span className="mono border border-border px-1.5 py-0.5 text-[9px] uppercase tracking-[0.16em] text-ink-soft">
                                Soon
                              </span>
                            ) : null}
                          </span>
                          <span className="mt-0.5 block text-[12px] leading-5 text-ink-soft">
                            {link.detail}
                          </span>
                        </div>
                      ),
                    )}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Nav() {
  const pathname = usePathname();
  const pageLabel = pageLabelFromPathname(pathname);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const closeTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openMenu = (groupId: string) => {
    if (closeTimeout.current) clearTimeout(closeTimeout.current);
    if (openMenuId !== groupId) {
      trackMarketingEvent("resource nav opened", { menu: groupId });
    }
    setOpenMenuId(groupId);
  };
  const closeMenuSoon = () => {
    if (closeTimeout.current) clearTimeout(closeTimeout.current);
    closeTimeout.current = setTimeout(() => setOpenMenuId(null), NAV_DROPDOWN_CLOSE_DELAY_MS);
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-6 md:px-10">
        <div className="flex min-w-0 items-center gap-8">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/"
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
            </Link>
            {pageLabel ? (
              <div className="flex min-w-0 items-center gap-2 text-[16px] font-semibold leading-none" aria-label={`Current page: ${pageLabel}`}>
                <span className="text-ink-soft" aria-hidden="true">/</span>
                <span className="truncate text-ink">{pageLabel}</span>
              </div>
            ) : null}
          </div>
          <nav className="hidden items-center gap-7 md:flex" aria-label="Primary">
            <NavDropdown
              columns={3}
              groups={RESOURCE_GROUPS}
              label="Resources"
              open={openMenuId === "resources"}
              onOpen={() => openMenu("resources")}
              onCloseSoon={closeMenuSoon}
            />
            <NavDropdown
              columns={4}
              groups={INTEGRATE_GROUPS}
              label="Integrate"
              open={openMenuId === "integrate"}
              onOpen={() => openMenu("integrate")}
              onCloseSoon={closeMenuSoon}
            />
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
            href={SIGN_IN_HREF}
            className="hidden text-[13px] text-ink-soft transition-colors hover:text-ink md:inline"
          >
            Sign in
          </a>
          <Link
            href={EARLY_ACCESS_HREF}
            onClick={() =>
              {
                const properties = {
                  cta: "nav request early access",
                  destination: EARLY_ACCESS_HREF,
                };
                trackMarketingEvent("cta clicked", properties);
                trackMarketingEvent("early access intent started", properties);
              }
            }
            className="inline-flex h-8 items-center gap-2 bg-ink px-3 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Request access
            <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
