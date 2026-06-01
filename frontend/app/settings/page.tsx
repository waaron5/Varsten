"use client";

import { useApiKey } from "@/components/providers";

export default function SettingsPage() {
  const { apiKey, ready, clearApiKey } = useApiKey();

  return (
    <div className="view" style={{ maxWidth: 820 }}>
      <div className="page-head">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-sub">Project connection and workspace configuration.</div>
        </div>
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, marginBottom: 10 }}>Connected key</h3>
        {!ready ? (
          <div className="spinner" />
        ) : apiKey ? (
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="pill neutral mono">{apiKey.slice(0, 10)}…</span>
            <button className="btn" onClick={() => clearApiKey()}>Disconnect</button>
          </div>
        ) : (
          <p className="page-sub" style={{ margin: 0 }}>No key connected. Add one from Setup.</p>
        )}
      </div>

      <div className="card card-pad">
        <h3 style={{ fontSize: 14, marginBottom: 6 }}>Organization, projects & budgets</h3>
        <p className="page-sub" style={{ margin: 0 }}>
          Org management, project switching, API key rotation, and the monthly AI spend budget
          land here alongside OAuth sign-in (build step 12).
        </p>
      </div>
    </div>
  );
}
