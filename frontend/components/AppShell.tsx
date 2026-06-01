"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApiKey } from "./providers";

const NAV: { href: string; label: string; icon: string }[] = [
  { href: "/", label: "Overview", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
  { href: "/explorer", label: "Usage Explorer", icon: "M3 3v18h18 M7 14l3-4 3 3 4-6" },
  { href: "/breakdowns", label: "Providers & Models", icon: "M12 2l9 4.5v11L12 22l-9-4.5v-11L12 2z M3 7l9 4.5 9-4.5 M12 11.5V22" },
  { href: "/setup", label: "Setup", icon: "M14 7a4 4 0 1 1-3.9 5H6v3H3v-3l3.1-3.1A4 4 0 0 1 14 7z M15 8.5h.01" },
  { href: "/settings", label: "Settings", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 6.6 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 13.4H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 6.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 10 4.6V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8 1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" },
];

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { apiKey } = useApiKey();
  const current = NAV.find((n) => n.href === pathname) ?? NAV[0];

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 17l5-6 4 4 6-8" />
            </svg>
          </div>
          <div className="brand-name">
            Vars<b>ten</b>
          </div>
        </div>
        <nav className="nav">
          <div className="nav-group-label">Workspace</div>
          {NAV.map((n) => {
            const active = n.href === pathname;
            return (
              <Link key={n.href} href={n.href} className={`nav-item${active ? " active" : ""}`}>
                <Icon path={n.icon} />
                {n.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumb">
            <span>Varsten</span>
            <span className="sep">/</span>
            <b>{current.label}</b>
          </div>
          <div className="topbar-actions">
            <span className={`pill ${apiKey ? "green" : "amber"}`}>
              <span className="dotp" style={{ background: apiKey ? "var(--pos)" : "var(--warn)" }} />
              {apiKey ? "Key connected" : "No key"}
            </span>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
