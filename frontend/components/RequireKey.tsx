"use client";

import Link from "next/link";
import { useApiKey } from "./providers";

// Gate for pages that need an API key. Waits for localStorage to be read to
// avoid a flash of the empty state on refresh.
export function RequireKey({ children }: { children: React.ReactNode }) {
  const { apiKey, ready } = useApiKey();

  if (!ready) {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
        <div className="spinner" />
      </div>
    );
  }

  if (!apiKey) {
    return (
      <div className="view">
        <div className="empty">
          <div className="et">Connect a project key to see your data</div>
          <div className="es">
            Generate a key for your project and paste it into Setup. The dashboard reads
            usage and spend through that key.
          </div>
          <Link href="/setup" className="btn primary">
            Go to Setup
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
