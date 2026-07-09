"use client";

import { useState } from "react";
import { trackMarketingEvent } from "./analytics/AnalyticsProvider";

export function TrackedCodeBlock({
  code,
  language,
  docSlug,
}: {
  code: string;
  language?: string;
  docSlug: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    trackMarketingEvent("docs code copied", {
      doc_slug: docSlug,
      language: language || "text",
    });
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="my-6 border border-border bg-ink text-primary-foreground">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2">
        <span className="mono text-[10px] uppercase tracking-[0.22em] text-white/45">
          {language || "text"}
        </span>
        <button
          type="button"
          onClick={copyCode}
          className="text-[12px] font-medium text-white/70 transition-colors hover:text-white"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-[13px] leading-6">
        <code>{code}</code>
      </pre>
    </div>
  );
}
