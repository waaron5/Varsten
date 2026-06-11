"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { OperatorProvisionResponse, OperatorValidationSummary } from "@/lib/types";
import { useSession } from "@/components/session";

function fieldId(name: string) {
  return `operator-${name}`;
}

export function OperatorOnboardingView() {
  const { getToken } = useSession();
  const [customerEmail, setCustomerEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [projectName, setProjectName] = useState("Production");
  const [apiKeyName, setApiKeyName] = useState("Production ingestion");
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [proofBusy, setProofBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [provisioned, setProvisioned] = useState<OperatorProvisionResponse | null>(null);
  const [summary, setSummary] = useState<OperatorValidationSummary | null>(null);

  function updateCompany(value: string) {
    setCompanyName(value);
    setOrganizationName((current) => (!current.trim() || current === companyName ? value : current));
  }

  async function provision(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setProvisioned(null);
    try {
      const response = await api.operatorProvision(await getToken(), {
        customer_email: customerEmail.trim(),
        full_name: fullName.trim(),
        company_name: companyName.trim(),
        organization_name: (organizationName || companyName).trim(),
        project_name: projectName.trim(),
        api_key_name: apiKeyName.trim(),
      });
      setProvisioned(response);
      setProjectId(response.project_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadSummary(event: FormEvent) {
    event.preventDefault();
    if (!projectId.trim()) return;
    setProofBusy(true);
    setError(null);
    setSummary(null);
    try {
      setSummary(await api.operatorValidationSummary(await getToken(), projectId.trim(), 24));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProofBusy(false);
    }
  }

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <p className="eyebrow">Operator</p>
          <h1>White-glove onboarding</h1>
          <p className="muted-copy">
            Provision customer tenants, generate one-time keys, and draft the 24-hour proof follow-up.
          </p>
        </div>
      </div>

      {error ? <div className="alert danger">{error}</div> : null}

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head">
            <h3>Provision customer</h3>
          </div>
          <form className="config-form" onSubmit={provision}>
            <label htmlFor={fieldId("email")}>Business email</label>
            <input
              id={fieldId("email")}
              className="input"
              type="email"
              value={customerEmail}
              onChange={(e) => setCustomerEmail(e.target.value)}
              required
            />
            <label htmlFor={fieldId("name")}>Full name</label>
            <input
              id={fieldId("name")}
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
            <label htmlFor={fieldId("company")}>Company name</label>
            <input
              id={fieldId("company")}
              className="input"
              value={companyName}
              onChange={(e) => updateCompany(e.target.value)}
              required
            />
            <label htmlFor={fieldId("org")}>Organization name</label>
            <input
              id={fieldId("org")}
              className="input"
              value={organizationName}
              onChange={(e) => setOrganizationName(e.target.value)}
              required
            />
            <label htmlFor={fieldId("project")}>Project name</label>
            <input
              id={fieldId("project")}
              className="input"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              required
            />
            <label htmlFor={fieldId("key")}>API key name</label>
            <input
              id={fieldId("key")}
              className="input"
              value={apiKeyName}
              onChange={(e) => setApiKeyName(e.target.value)}
              required
            />
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? "Provisioning..." : "Provision tenant and key"}
            </button>
          </form>

          {provisioned ? (
            <div className="code" style={{ marginTop: 16 }}>
              <div>Project: {provisioned.project_id}</div>
              <div>Key prefix: {provisioned.api_key_prefix}</div>
              <div>One-time key: {provisioned.plaintext_api_key}</div>
              <div style={{ marginTop: 12 }}>
                Transfer this key with 1Password Send or another secure temporary link. Do not email it.
              </div>
            </div>
          ) : null}
        </div>

        <div className="card">
          <div className="card-head">
            <h3>24-hour validation</h3>
          </div>
          <form className="config-form" onSubmit={loadSummary}>
            <label htmlFor={fieldId("project-id")}>Project ID</label>
            <input
              id={fieldId("project-id")}
              className="input"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="Project UUID"
              required
            />
            <button className="btn" type="submit" disabled={proofBusy || !projectId.trim()}>
              {proofBusy ? "Loading..." : "Draft follow-up"}
            </button>
          </form>

          {summary ? (
            <div style={{ marginTop: 16 }}>
              <div className="metric-grid">
                <div className="metric">
                  <span>Requests</span>
                  <b>{summary.request_count.toLocaleString()}</b>
                </div>
                <div className="metric">
                  <span>p95 latency</span>
                  <b>{summary.p95_latency_ms === null ? "-" : `${summary.p95_latency_ms}ms`}</b>
                </div>
                <div className="metric">
                  <span>Saved</span>
                  <b>{summary.saved_usd === null ? "-" : `$${summary.saved_usd}`}</b>
                </div>
              </div>
              <textarea className="input" readOnly rows={8} value={summary.follow_up_draft} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
